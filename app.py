from flask import Flask, request, jsonify, send_file, g, abort
from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, fields, exceptions as marshmallow_exceptions
from makeflop import Floppy
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
import string
import random
import os
import shutil
import datetime


class KickstartFloppyCreate(Schema):
    hostname = fields.Str(required=True)
    rootpw = fields.Str(required=True)
    disk = fields.Str(required=True)
    device = fields.Str(required=False, load_default='vmnic0')
    ip = fields.IPv4(required=True)
    netmask = fields.IPv4(required=True)
    gateway = fields.IPv4(required=True)
    nameserver = fields.List(fields.IPv4(), required=True)
    vlanid = fields.Int(required=False, min=0, max=4094, load_default=0)
    addvmportgroup = fields.Bool(required=False, load_default=True)
    allowed_ip = fields.IPv4(required=True)


db = SQLAlchemy()
app = Flask(__name__)
DATABASE = 'ks.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DATABASE
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
db.init_app(app)

class KickstartFloppy(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    image_file: Mapped[str] = mapped_column(unique=True)
    allowed_ip: Mapped[str]
    expires_at: Mapped[str]
    
    def __init__(self, image_file, allowed_ip, expires_at):
        self.image_file = image_file
        self.allowed_ip = allowed_ip
        self.expires_at = expires_at
    

    def toJSON(self):
        return {
            'image_file': self.image_file,
            'allowed_ip': self.allowed_ip,
            'expires_at': self.expires_at
        }


with app.app_context():
    db.create_all()


@app.route('/ks', methods=['POST'])
def create_kickstart_floppy():
    schema = KickstartFloppyCreate()
    if request.is_json:
        try:
            body = schema.load(request.get_json())
        except marshmallow_exceptions.ValidationError as err:
            return jsonify(err.messages), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        return jsonify({"error": "Request must be JSON"}), 400
    kickstart_contents = """vmaccepteula
rootpw --iscrypted {rootpw}
install --disk={disk}
network --bootproto=static --device={device} --ip={ip}  --gateway={gateway} --nameserver={nameserver} --netmask={netmask} --hostname={hostname} --vlanid={vlanid} --addvmportgroup={addvmportgroup}
reboot
""".format(
        rootpw=body['rootpw'],
        disk=body['disk'],
        device=body['device'],
        ip=body['ip'],
        gateway=body['gateway'],
        nameserver=",".join(str(x) for x in body['nameserver']),
        netmask=body['netmask'],
        hostname=body['hostname'],
        vlanid=body['vlanid'],
        addvmportgroup=int(body['addvmportgroup'])
    )
    floppy = Floppy()
    floppy.add_file_path('ks.cfg', kickstart_contents.encode('utf-8'))
    image_file = ''.join(random.choices(string.ascii_letters + string.digits, k=8)) + '.img'
    floppy.save(os.path.join(app.instance_path, image_file))
    current_time = datetime.datetime.now()
    expires_at = current_time + datetime.timedelta(minutes=60)
    allowed_ip = str(body['allowed_ip'])
    floppy_data = KickstartFloppy(image_file, allowed_ip, expires_at)
    db.session.add(floppy_data)
    db.session.commit()
    return jsonify(floppy_data.toJSON()), 201


@app.route('/ks/<string:image_file>', methods=['GET'])
def get_kickstart_floppy(image_file):
    floppy = db.session.execute(db.select(KickstartFloppy).filter_by(image_file=image_file)).scalar_one_or_none()

    if floppy.allowed_ip != request.remote_addr[0]:
        return jsonify({"error": "Your IP is not permitted to access this resource"}), 401
    return send_file("ks/" + image_file)


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
