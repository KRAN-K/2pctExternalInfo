import os, io, random, zipfile, sqlite3, struct, wave, hashlib, json
from PIL import Image
rnd=random.Random(5)
files={}
def rimg(w,h,fmt,**kw):
    im=Image.frombytes("RGB",(w,h),bytes(rnd.getrandbits(8) for _ in range(w*h*3)))
    b=io.BytesIO(); im.save(b,fmt,**kw); return b.getvalue()
files['a.jpg']=rimg(300,200,'JPEG',quality=85)
files['b_prog.jpg']=rimg(400,300,'JPEG',progressive=True)
files['c.png']=rimg(200,200,'PNG')
files['d.gif']=rimg(100,100,'GIF')
files['e.bmp']=rimg(120,80,'BMP')
b=io.BytesIO()
with zipfile.ZipFile(b,'w') as z:
    z.writestr('[Content_Types].xml','x'*500); z.writestr('word/document.xml',os.urandom(20000))
files['f.docx']=b.getvalue()
files['g.pdf']=b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"+os.urandom(3000).replace(b"%%EOF",b"xxxxx")+b"\nxref\n0 1\ntrailer<<>>\nstartxref\n9\n%%EOF\n"
def atom(t,d): return struct.pack(">I",8+len(d))+t+d
files['h.mp4']=atom(b'ftyp',b'isom\0\0\2\0isomiso2')+atom(b'moov',os.urandom(3000))+atom(b'mdat',os.urandom(50000))
w=io.BytesIO()
with wave.open(w,'wb') as wf:
    wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(8000);wf.writeframes(os.urandom(16000))
files['i.wav']=w.getvalue()
c=sqlite3.connect('x.db');c.execute('create table t(a)');c.executemany('insert into t values(?)',[(os.urandom(100),) for _ in range(300)]);c.commit();c.close()
files['j.db']=open('x.db','rb').read()
img=bytearray(); meta={}
for n,d in files.items():
    img+=os.urandom(rnd.randrange(3,40)*512+rnd.randrange(0,512))
    img+=b'\0'*((-len(img))%512)
    meta[n]=(len(img),hashlib.sha256(d).hexdigest()); img+=d
img+=os.urandom(100000)
img[777:780]=b'\xff\xd8\xff'
open('card.img','wb').write(img); json.dump(meta,open('meta.json','w'))
print(len(img),'bytes',len(files),'files')
