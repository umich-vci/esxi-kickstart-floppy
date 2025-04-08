# esxi-kickstart-floppy

This is a [APIFlask](https://apiflask.com/) based application that provides a REST endpoint
for generating kickstart files for provisioning an ESXi host and placing them on a floppy image.
The floppy is formatted such that it is detected by ESXi as a USB drive (at least on HPE iLO).
Additionally, while the image is served without authentication, access to the generated image
is restricted to a single IP address (i.e. an iLO or similar) to reduce the risk of leaking
credentials.  These generated files are automatically cleaned up after 1 hour.

You can also upload ESXi images to be served out by the application and newly uploaded images will
automatically be adjusted to add `ks=usb` to the `boot.cfg` files on the ISO.

APIFlask also provides a Swagger UI that makes it easy to understand and use the API initially.
It is available at the `/docs` endpoint.

By default, the application will generate a new API token every startup.  Persistent tokens
can be created by adding the file `tokens.py` to the instance directory. Here is an example:
```python
# you can generate a token with secrets.token_urlsafe()
TOKENS = {"YOURTOKENHERE": "description or name here"}
```

