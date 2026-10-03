"""Step 6 feasibility (PROJE.md §4.5): Fomo's Solana trades from the free public websocket, one minute.

  python scripts/solana_probe.py      (needs: pip install websockets base58)

Fomo signs and pays gas for every Solana trade with one wallet (FEE_PAYER, public knowledge: Bitquery's FOMO API
docs), so logsSubscribe(mentions=[FEE_PAYER]) streams every Fomo trade's logs live. pump.fun's TradeEvent sits in
the logs ("Program data:", discriminator TRADE): mint, SOL in/out, tokens, buy/sell, user, time.
"""
import asyncio, json, time, base64, collections, struct, websockets, base58
FEE_PAYER = "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"; PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TRADE = bytes.fromhex("bddb7fd34ee661ee")
async def main():
    n=0; kinds=collections.Counter(); t0=time.time(); dec=[]
    async with websockets.connect("wss://api.mainnet-beta.solana.com", max_size=2**24) as ws:
        await ws.send(json.dumps({"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[{"mentions":[FEE_PAYER]},{"commitment":"confirmed"}]}))
        await ws.recv()
        while time.time()-t0<60:
            try: msg=json.loads(await asyncio.wait_for(ws.recv(),10))
            except asyncio.TimeoutError: continue
            v=msg.get("params",{}).get("result",{}).get("value",{})
            if not v or v.get("err"): continue
            n+=1; logs=v.get("logs",[]); txt=" ".join(logs)
            pump_ev=None
            for l in logs:
                if l.startswith("Program data:"):
                    b=base64.b64decode(l.split(":",1)[1].strip())
                    if b[:8]==TRADE: pump_ev=b
            if pump_ev: kinds["pump.fun curve"]+=1
            elif PUMPSWAP in txt: kinds["PumpSwap AMM"]+=1
            elif "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo" in txt: kinds["Meteora"]+=1
            elif "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" in txt or "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C" in txt or "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK" in txt: kinds["Raydium"]+=1
            else: kinds["diğer"]+=1
            if pump_ev and len(dec)<3:
                mint=base58.b58encode(pump_ev[8:40]).decode(); sol,tok=struct.unpack_from("<QQ",pump_ev,40); buy=pump_ev[56]
                user=base58.b58encode(pump_ev[57:89]).decode(); ts=struct.unpack_from("<q",pump_ev,89)[0]
                dec.append((mint[:10], sol/1e9, tok/1e6, "alım" if buy else "satım", user[:8], time.strftime('%H:%M:%S',time.gmtime(ts))))
    print(n,"başarılı Fomo işlemi / 60 sn ·", dict(kinds))
    for d in dec: print("çözülen pump.fun işlemi:", d)
asyncio.run(main())
