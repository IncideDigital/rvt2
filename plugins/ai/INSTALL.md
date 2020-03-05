# Info
Modules to classify images using Neural Net models.

Classifier models are extracted from

https://github.com/GantMan/nsfw_model
https://github.com/bedapudi6788/NudeNet

By default it will use GantMan classifier although it will use InceptionV3 if model is misconfigured.

# Installation

Install keras and tensorflow with pipenv install, and download classifier models:

- https://github.com/bedapudi6788/NudeNet/releases/download/v0/classifier_model
- https://s3.amazonaws.com/nsfwdetector/nsfw.299x299.h5

And copy them into `models` folder.

```
pip3 install --user numpy tensorflow keras
mkdir models
cd models
wget https://github.com/bedapudi6788/NudeNet/releases/download/v0/classifier_model
wget https://s3.amazonaws.com/nsfwdetector/nsfw.299x299.h5
```

Also, add this configuration to `local.cfg`:

```
[rvt2]
plugins:
    ...
    DOWNLOAD_FOLDER
```

