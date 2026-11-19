import asyncio, httpx, websockets
BASE="http://127.0.0.1:8080"; PORTAL="http://portal.127.0.0.1.nip.io:8080"; WID="319fc425-cf45-4307-b4a9-b693fe67cad9"
async def main():
  async with httpx.AsyncClient(timeout=20) as c:
    r=await c.post(PORTAL+"/api/auth/login",json={"login":"a1","password":"Str0ngPassw0rd!x"},headers={"Origin":PORTAL})
    csrf=r.json()["csrf_token"]
    r=await c.post(PORTAL+f"/api/workspaces/{WID}/entry-tickets",json={"target":"agent"},headers={"Origin":PORTAL,"X-CSRF-Token":csrf})
    j=r.json(); h=j["workspace_host"]
    r=await c.post(BASE+"/_platform/enter",data={"ticket":j["ticket"]},headers={"Host":h,"Origin":PORTAL},follow_redirects=False)
    cookie=r.headers["set-cookie"].split(";",1)[0]
  ws=await websockets.connect(f"ws://{h}/api/remote.mux",additional_headers={"Origin":"http://"+h,"Cookie":cookie})
  print("connected")
  try:
    for i in range(5):
      try:
        m=await asyncio.wait_for(ws.recv(),timeout=1.0)
        print("MSG",str(m)[:200])
      except asyncio.TimeoutError:
        print("tick",i)
  except Exception as e:
    print("CLOSED",type(e).__name__,str(e)[:200])
  await ws.close()
asyncio.run(main())
