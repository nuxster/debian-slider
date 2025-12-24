.PHONY: install uninstall apply apply-now set-default

themes-path = /usr/share/plymouth/themes
debian-slider-path = $(themes-path)/debian-slider

uninstall:
	rm -rv $(debian-slider-path) >/dev/null 2>&1 || true

install: uninstall
	mkdir -p $(debian-slider-path)
	cp -Rv theme/* $(debian-slider-path)

apply: install
ifneq ($(shell which plymouth-set-default-theme),)
	plymouth-set-default-theme debian-slider
else ifneq ($(shell which update-alternatives),)
	update-alternatives --install $(themes-path)/default.plymouth default.plymouth $(debian-slider-path)/debian-slider.plymouth 10
	update-alternatives --set default.plymouth $(debian-slider-path)/debian-slider.plymouth
else
	$(error "neither plymouth-set-default-theme nor update-alternatives is in PATH")
endif

apply-now: apply
ifneq ($(shell which plymouth-set-default-theme),)
	plymouth-set-default-theme -R debian-slider || true
else ifneq ($(shell which update-alternatives),)
	update-initramfs -u
endif

set-default: apply-now
	$(warning warning: target 'set-default' is deprecated, use 'apply-now' instead)