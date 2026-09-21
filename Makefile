THEME       := debian-slider
PREFIX      ?= /usr
DESTDIR     ?=
THEMES_DIR  := $(PREFIX)/share/plymouth/themes
THEME_DIR   := $(THEMES_DIR)/$(THEME)
PYTHON      ?= python3
PREVIEW_SECONDS ?= 8
# tools/render.py options, e.g. RENDER_FLAGS="--color 3b82f6"
RENDER_FLAGS ?=

.DEFAULT_GOAL := help
.PHONY: help check render logo install uninstall apply apply-now set-default preview

help:
	@echo "Targets:"
	@echo "  check      validate theme files (no root needed)"
	@echo "  render     regenerate theme/images from src/logo.png (see tools/render.py --help)"
	@echo "  logo       re-render src/logo.png from src/logo.svg (needs ImageMagick or rsvg-convert)"
	@echo "  install    copy the theme to $(THEME_DIR) (honours DESTDIR/PREFIX)"
	@echo "  uninstall  remove the installed theme"
	@echo "  apply      install and make it the default theme"
	@echo "  apply-now  apply and rebuild the initramfs"
	@echo "  preview    show the current default theme for $(PREVIEW_SECONDS)s (needs plymouth-x11)"

check:
	$(PYTHON) tools/check.py theme

render:
	$(PYTHON) tools/render.py $(RENDER_FLAGS)

logo:
	@if command -v rsvg-convert >/dev/null 2>&1; then \
		rsvg-convert -h 600 -o src/logo.png src/logo.svg; \
	elif command -v magick >/dev/null 2>&1; then \
		magick -background none -density 600 src/logo.svg -trim +repage -resize x600 -strip PNG32:src/logo.png; \
	else \
		echo "error: need rsvg-convert (librsvg2-bin) or magick (imagemagick)" >&2; exit 1; \
	fi

uninstall:
	rm -rf "$(DESTDIR)$(THEME_DIR)"

# Stale files from an older version (two-step frames, keymap strip) must not
# linger next to the script, so the target directory is recreated from scratch.
install: uninstall
	install -d "$(DESTDIR)$(THEME_DIR)"
	for set in theme/images/*x; do \
		install -d "$(DESTDIR)$(THEME_DIR)/images/$$(basename $$set)"; \
		install -m 0644 $$set/*.png "$(DESTDIR)$(THEME_DIR)/images/$$(basename $$set)/"; \
	done
	install -m 0644 theme/$(THEME).script "$(DESTDIR)$(THEME_DIR)/$(THEME).script"
	sed -e 's|^ImageDir=.*|ImageDir=$(THEME_DIR)/images|' \
	    -e 's|^ScriptFile=.*|ScriptFile=$(THEME_DIR)/$(THEME).script|' theme/$(THEME).plymouth \
		> "$(DESTDIR)$(THEME_DIR)/$(THEME).plymouth"
	chmod 0644 "$(DESTDIR)$(THEME_DIR)/$(THEME).plymouth"

apply: install
	@if command -v plymouth-set-default-theme >/dev/null 2>&1; then \
		plymouth-set-default-theme $(THEME); \
	elif command -v update-alternatives >/dev/null 2>&1; then \
		update-alternatives --install $(THEMES_DIR)/default.plymouth default.plymouth $(THEME_DIR)/$(THEME).plymouth 10; \
		update-alternatives --set default.plymouth $(THEME_DIR)/$(THEME).plymouth; \
	else \
		echo "error: neither plymouth-set-default-theme nor update-alternatives is in PATH" >&2; exit 1; \
	fi

apply-now: apply
	@if command -v plymouth-set-default-theme >/dev/null 2>&1; then \
		plymouth-set-default-theme -R $(THEME); \
	else \
		update-initramfs -u; \
	fi

set-default: apply-now
	$(warning target 'set-default' is deprecated, use 'apply-now' instead)

preview:
	@command -v plymouthd >/dev/null 2>&1 || { echo "error: plymouthd not found, install plymouth-x11" >&2; exit 1; }
	plymouthd
	plymouth --show-splash
	sleep $(PREVIEW_SECONDS)
	plymouth update --status=display-manager.service   # end of boot: full bar
	sleep 1
	plymouth --quit
