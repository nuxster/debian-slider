# Debian Slider Plymouth Theme

Simple Plymouth boot splash theme with password support.

<img src="./preview.gif" alt="Debian Slider Plymouth Theme preview" style="max-width: 400px; height: auto;">


## Installation
```shell
git clone https://github.com/nuxster/debian-slider.git
cd debian-slider
sudo make apply-now

# For testing in X11 and Wayland
sudo apt install plymouth-x11
sudo plymouthd; sudo plymouth --show-splash; sleep 5; sudo plymouth --quit
```
