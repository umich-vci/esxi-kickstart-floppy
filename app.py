from flask import Flask, request, jsonify, send_file, g
from flask_apscheduler import APScheduler
from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, fields, exceptions as marshmallow_exceptions
from makeflop import Floppy
from sqlalchemy.orm import Mapped, mapped_column
import string
import random
import os
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
    id = db.Column(db.Integer, primary_key=True)
    image_file = db.Column(db.String(12), unique=True, nullable=False)
    allowed_ip = db.Column(db.String(15), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    
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

scheduler = APScheduler()
scheduler.init_app(app)
@scheduler.task('interval', id='cleanup', seconds=60)
def cleanup():
    with app.app_context():
        cleanup = KickstartFloppy.query.filter(KickstartFloppy.expires_at < datetime.datetime.now()).all()
        if len(cleanup) > 0:
            app.logger.info(f"{len(cleanup)} expired entries found")
        for item in cleanup:
            app.logger.info(f"Deleting expired entry: {item.image_file}")
            image_path = os.path.join(app.instance_path, item.image_file)
            os.remove(image_path)
            db.session.delete(item)
        db.session.commit()

scheduler.start()

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
    app.logger.info(f"Created {image_file} with access for {allowed_ip}")
    return jsonify(floppy_data.toJSON()), 201


@app.route('/ks/<string:image_file>', methods=['GET'])
def get_kickstart_floppy(image_file):
    floppy = db.session.execute(db.select(KickstartFloppy).filter_by(image_file=image_file)).scalar_one_or_none()

    if floppy is None:
        return jsonify({"error": "File not found"}), 404

    if floppy.allowed_ip != request.remote_addr[0]:
        return jsonify({"error": "Your IP is not permitted to access this resource"}), 401
    
    image_path = os.path.join(app.instance_path, image_file)
    if not os.path.exists(image_path):
        return jsonify({"error": "File not found"}), 404
    
    app.logger.info(f"Serving {image_file} for {request.remote_addr[0]}")
    return send_file("ks/" + image_file)

if __name__ == '__main__':
    app.run()
