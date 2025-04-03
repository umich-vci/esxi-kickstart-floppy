from flask import request, send_file, url_for
from apiflask import APIFlask, abort, HTTPTokenAuth, FileSchema, Schema
from flask_apscheduler import APScheduler
from flask_sqlalchemy import SQLAlchemy
from apiflask.fields import Integer, String, IPv4, List, Boolean, DateTime
from apiflask.validators import Range
from makeflop import Floppy
import string
import random
import os
import secrets
import datetime


class KickstartFloppyIn(Schema):
    hostname = String(required=True)
    rootpw = String(required=True)
    disk = String(required=True)
    device = String(required=False, load_default='vmnic0')
    ip = IPv4(required=True)
    netmask = IPv4(required=True)
    gateway = IPv4(required=True)
    nameserver = List(IPv4(), required=True)
    vlanid = Integer(required=False, validate=Range(min=1, max=4094))
    addvmportgroup = Boolean(required=False, load_default=True)
    allowed_ip = IPv4(required=True)


class KickstartFloppyOut(Schema):
    image_file = String(required=True)
    image_url = String(required=True)
    allowed_ip = String(required=True)
    expires_at = DateTime(required=True)


db = SQLAlchemy()
app = APIFlask(__name__)
application = app # for mod_wsgi compatibility
DATABASE = 'ks.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DATABASE
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
db.init_app(app)
auth = HTTPTokenAuth()
try:
    app.config.from_pyfile(os.path.join(app.instance_path, 'tokens.py'))
except FileNotFoundError:
    app.logger.warning("tokens.py not found, generating default token")
    app.config['TOKENS'] = {secrets.token_urlsafe(): 'default'}
    print(app.config['TOKENS'])
tokens = app.config['TOKENS']


class KickstartFloppyModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_file = db.Column(db.String(12), unique=True, nullable=False)
    image_url = db.Column(db.String(255), unique=True, nullable=False)
    allowed_ip = db.Column(db.String(39), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)

    def __init__(self, image_file, image_url, allowed_ip, expires_at):
        self.image_file = image_file
        self.image_url = image_url
        self.allowed_ip = allowed_ip
        self.expires_at = expires_at


with app.app_context():
    db.create_all()


scheduler = APScheduler()
scheduler.init_app(app)


@scheduler.task('interval', id='cleanup', seconds=60)
def cleanup():
    with app.app_context():
        cleanup = KickstartFloppyModel.query.filter(
            KickstartFloppyModel.expires_at < datetime.datetime.now()).all()
        if len(cleanup) > 0:
            app.logger.info(f"{len(cleanup)} expired entries found")
            for item in cleanup:
                app.logger.info(f"Deleting expired entry: {item.image_file}")
                image_path = os.path.join(app.instance_path, item.image_file)
                os.remove(image_path)
                db.session.delete(item)
            db.session.commit()


scheduler.start()


@auth.verify_token
def verify_token(token):
    if token in tokens:
        return tokens[token]


@app.post('/ks')
@app.auth_required(auth)
@app.input(KickstartFloppyIn, location='json')
@app.output(KickstartFloppyOut, status_code=201)
def create_kickstart_floppy(json_data):
    if 'vlanid' in json_data:
        vlanid = f" --vlanid={json_data['vlanid']}"
    else:
        vlanid = ""
    kickstart_contents = """vmaccepteula
rootpw --iscrypted {rootpw}
install --disk={disk}
network --bootproto=static --device={device} --ip={ip} --gateway={gateway} --nameserver={nameserver} --netmask={netmask} --hostname={hostname} --addvmportgroup={addvmportgroup}{vlanid}
reboot
""".format(
        rootpw=json_data['rootpw'],
        disk=json_data['disk'],
        device=json_data['device'],
        ip=json_data['ip'],
        gateway=json_data['gateway'],
        nameserver=",".join(str(x) for x in json_data['nameserver']),
        netmask=json_data['netmask'],
        hostname=json_data['hostname'],
        addvmportgroup=int(json_data['addvmportgroup']),
        vlanid=vlanid,
    )
    floppy = Floppy()
    floppy.add_file_path('ks.cfg', kickstart_contents.encode('utf-8'))
    image_file = ''.join(
        random.choices(string.ascii_letters + string.digits, k=8)) + '.img'
    floppy.save(os.path.join(app.instance_path, image_file))
    current_time = datetime.datetime.now()
    expires_at = current_time + datetime.timedelta(minutes=60)
    allowed_ip = str(json_data['allowed_ip'])
    image_url = url_for('get_kickstart_floppy', image_file=image_file,
                        _external=True)
    floppy_data = KickstartFloppyModel(image_file, image_url, allowed_ip, expires_at)
    db.session.add(floppy_data)
    db.session.commit()
    app.logger.info(f"Created {image_file} with access for {allowed_ip}")
    return floppy_data


@app.get('/ks/<string:image_file>')
@app.output(FileSchema,
            content_type='application/octet-stream', status_code=200)
def get_kickstart_floppy(image_file):
    floppy = db.session.execute(
        db.select(KickstartFloppyModel).filter_by(
            image_file=image_file)).scalar_one_or_none()

    if floppy is None:
        abort(404, 'File not found')

    if floppy.allowed_ip != request.remote_addr:
        abort(401, f'{request.remote_addr} is not permitted')

    image_path = os.path.join(app.instance_path, image_file)
    if not os.path.exists(image_path):
        abort(404, 'File not found')

    app.logger.info(f"Serving {image_file} for {request.remote_addr[0]}")
    return send_file(image_path)


if __name__ == '__main__':
    app.run()
