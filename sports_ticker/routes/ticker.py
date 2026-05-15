import uuid
from flask import request, jsonify
from ..routes_runtime import app
from ..core import (
    tickers,
    pair_client_to_ticker, create_ticker_record, save_specific_ticker, generate_pairing_code,
)

@app.route('/pair', methods=['POST'])
def pair_ticker():
    try:
        cid = request.headers.get('X-Client-ID')
        json_body = request.json or {}
        code = json_body.get('code')
        friendly_name = json_body.get('name', 'My Ticker')
        
        print(f"🔗 Pairing Attempt from Client: {cid} | Code: {code}")

        if not cid or not code:
            print("❌ Missing CID or Code")
            return jsonify({"success": False, "message": "Missing Data"}), 400
        
        input_code = str(code).strip()

        for uid, rec in tickers.items():
            known_code = str(rec.get('pairing_code', '')).strip()
            
            if known_code == input_code:
                pair_client_to_ticker(rec, cid, friendly_name)
                save_specific_ticker(uid)
                
                print(f"✅ Paired Successfully to Ticker: {uid}")
                return jsonify({"success": True, "ticker_id": uid})
        
        print(f"❌ Invalid Code. Input: {input_code}")
        return jsonify({"success": False, "message": "Invalid Pairing Code"}), 200

    except Exception as e:
        print(f"🔥 Pairing Server Error: {e}")
        return jsonify({"success": False, "message": "Server Logic Error"}), 500


@app.route('/pair/id', methods=['POST'])
def pair_ticker_by_id():
    cid = request.headers.get('X-Client-ID')
    tid = request.json.get('id')
    friendly_name = request.json.get('name', 'My Ticker')
    
    if not cid or not tid: return jsonify({"success": False}), 400
    
    if tid in tickers:
        pair_client_to_ticker(tickers[tid], cid, friendly_name)
        save_specific_ticker(tid)
        return jsonify({"success": True, "ticker_id": tid})
        
    return jsonify({"success": False}), 404


@app.route('/register', methods=['POST'])
def register_ticker():
    """Register a new ticker and auto-pair the requesting client."""
    try:
        cid = request.headers.get('X-Client-ID')
        json_body = request.json or {}
        friendly_name = json_body.get('name', 'My Ticker')

        if not cid:
            return jsonify({"success": False, "message": "Missing X-Client-ID header"}), 400

        # Check if this client already owns a ticker — return it instead of creating a duplicate
        for tid, rec in tickers.items():
            if cid in rec.get('clients', []):
                print(f"🔁 Client {cid} already owns ticker {tid}, returning existing")
                return jsonify({"success": True, "ticker_id": tid})

        # Generate a unique ticker ID
        new_tid = str(uuid.uuid4())

        tickers[new_tid] = create_ticker_record(name=friendly_name, client_id=cid)
        save_specific_ticker(new_tid)

        print(f"✅ Registered new ticker: {new_tid} (client: {cid})")
        return jsonify({"success": True, "ticker_id": new_tid})

    except Exception as e:
        print(f"🔥 Register Error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/ticker/<tid>/unpair', methods=['POST'])
def unpair(tid):
    cid = request.headers.get('X-Client-ID')
    if tid in tickers and cid in tickers[tid]['clients']:
        tickers[tid]['clients'].remove(cid)
        if not tickers[tid]['clients']: tickers[tid]['paired'] = False; tickers[tid]['pairing_code'] = generate_pairing_code()
        save_specific_ticker(tid)
    return jsonify({"success": True})


@app.route('/tickers', methods=['GET'])
def list_tickers():
    cid = request.headers.get('X-Client-ID'); 
    if not cid: return jsonify([])
    res = []
    for uid, rec in tickers.items():
        if cid in rec.get('clients', []): res.append({ "id": uid, "name": rec.get('name', 'Ticker'), "settings": rec['settings'], "last_seen": rec.get('last_seen', 0) })
    return jsonify(res)


