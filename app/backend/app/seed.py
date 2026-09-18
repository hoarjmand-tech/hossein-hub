from sqlalchemy import select
from .core import SessionLocal
from .models import ManagedAsset
DEFAULTS=[
 ("FortiGate","firewall","192.168.1.10",9042,"tcp","Gateway / FortiGate management"),
 ("DC-SRV","server","192.168.1.1",53,"tcp","Primary AD/DNS"),
 ("ADC-SRV","server","192.168.1.2",53,"tcp","Additional DC/DNS"),
 ("WSUS-SRV","server","192.168.1.24",8530,"tcp","WSUS"),
 ("MeshCentral","service","192.168.1.30",443,"tcp","Remote management"),
 ("PBX","service","192.168.1.223",80,"tcp","Panasonic KX-TDE200"),
 ("Hossein Hub","service","192.168.1.35",8080,"http","Hossein Hub"),
]
def run():
 with SessionLocal() as db:
  for name,kind,address,port,protocol,notes in DEFAULTS:
   if not db.scalar(select(ManagedAsset).where(ManagedAsset.name==name)):
    db.add(ManagedAsset(name=name,kind=kind,address=address,port=port,protocol=protocol,notes=notes,enabled=True))
  db.commit()
if __name__=="__main__":run()
