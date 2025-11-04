import os
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Session as SessionSchema

app = FastAPI(title="LoanLens AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------

def _col(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session id")


def _now():
    return datetime.utcnow()


def system_message(text: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": text, "timestamp": _now()}


# ---------- Models ----------

class ChatInput(BaseModel):
    session_id: Optional[str] = None
    message: str


# ---------- Routes ----------

@app.get("/")
def read_root():
    return {"message": "LoanLens AI Backend running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


@app.post("/api/session/start")
def start_session() -> Dict[str, Any]:
    session = SessionSchema()
    session_id = create_document("session", session)
    oid = _oid(session_id)
    welcome = system_message(
        "Hi! I’m your loan assistant. What’s your full name and the loan amount you’re looking for?"
    )
    _col("session").update_one({"_id": oid}, {"$push": {"messages": welcome}})
    return {"session_id": session_id, "message": welcome}


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    s = _col("session").find_one({"_id": _oid(session_id)})
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s["_id"] = str(s["_id"])  # serialize
    return s


def parse_int(text: str) -> Optional[int]:
    import re
    nums = re.findall(r"\d+", text.replace(",", ""))
    if not nums:
        return None
    try:
        return int(nums[0])
    except Exception:
        return None


@app.post("/api/chat/send")
def chat_send(payload: ChatInput):
    # Ensure session
    if payload.session_id:
        sid = payload.session_id
    else:
        sid = create_document("session", SessionSchema())
    oid = _oid(sid)

    session = _col("session").find_one({"_id": oid})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = {"role": "user", "content": payload.message, "timestamp": _now()}
    _col("session").update_one({"_id": oid}, {"$push": {"messages": user_msg}})

    stage = session.get("stage", "intro")
    text = payload.message.strip()

    reply = None

    if stage == "intro":
        amt = parse_int(text)
        name = None
        tl = text.lower()
        if "name is" in tl:
            name = text.split("is", 1)[1].strip()
        elif "i am" in tl:
            name = text.split("i am", 1)[1].strip()
        elif "i'm" in tl:
            name = text.split("i'm", 1)[1].strip()
        updates: Dict[str, Any] = {}
        if name:
            updates["customer_name"] = " ".join(name.split()[:3]).title()
        if amt:
            updates["requested_amount"] = amt
        if amt or name:
            updates["stage"] = "verification"
            reply = system_message(
                "Great. To proceed, please upload your KYC: PAN and Aadhaar. You can upload images (JPG/PNG) or PDF."
            )
        else:
            reply = system_message(
                "Got it. Please share your full name and the loan amount you need (e.g., 500000)."
            )
        if updates:
            _col("session").update_one({"_id": oid}, {"$set": updates})

    elif stage == "verification":
        reply = system_message(
            "Awaiting KYC documents. Upload PAN and Aadhaar to continue."
        )

    elif stage == "underwriting":
        income = parse_int(text)
        if income:
            _col("session").update_one({"_id": oid}, {"$set": {"monthly_income": income}})
            max_amount = min(income * 20, 500000)
            requested = session.get("requested_amount") or max_amount
            approved = min(requested, max_amount)
            status = "approved" if income >= 25000 and approved > 0 else "rejected"
            offer = {
                "requested": requested,
                "approved": approved,
                "rate": 14.0 if approved >= 300000 else 16.0,
                "tenure_months": 48 if approved >= 300000 else 36,
                "processing_fee": max(1999, int(approved * 0.01)),
                "status": status,
            }
            _col("session").update_one({"_id": oid}, {"$set": {"offer": offer, "stage": "sanction"}})
            if status == "approved":
                reply = system_message(
                    f"You're eligible. Approved amount: ₹{offer['approved']:,}. Shall I generate your sanction letter?"
                )
            else:
                reply = system_message(
                    "Based on your income, we can’t approve the requested amount at this time."
                )
        else:
            reply = system_message("Please share your monthly income (e.g., 30000).")

    elif stage == "sanction":
        if any(k in text.lower() for k in ["yes", "ok", "proceed", "generate", "sure"]):
            s = _col("session").find_one({"_id": oid})
            name = s.get("customer_name", "Customer")
            offer = s.get("offer", {})
            letter = generate_offer_letter(name, offer)
            _col("session").update_one({"_id": oid}, {"$set": {"offer.letter": letter, "stage": "complete"}})
            reply = system_message("Sanction letter generated. You can download it now.")
        else:
            reply = system_message("Say 'yes' to generate your sanction letter.")

    elif stage == "complete":
        reply = system_message("Your application is complete. How else can I help today?")

    _col("session").update_one({"_id": oid}, {"$push": {"messages": reply}})

    new_stage = _col("session").find_one({"_id": oid}).get("stage")
    return {"session_id": sid, "reply": reply, "stage": new_stage}


@app.post("/api/verification/upload")
async def verification_upload(
    session_id: str = Form(...),
    pan: UploadFile = File(...),
    aadhaar: UploadFile = File(...),
):
    allowed = {"image/jpeg", "image/png", "application/pdf"}
    for f in [pan, aadhaar]:
        if f.content_type not in allowed:
            raise HTTPException(status_code=400, detail=f"Invalid file type: {f.filename}")
        content = await f.read()
        if len(content) < 10 * 1024:
            raise HTTPException(status_code=400, detail=f"File too small/unclear: {f.filename}")

    oid = _oid(session_id)
    sdoc = _col("session").find_one({"_id": oid})
    if not sdoc:
        raise HTTPException(status_code=404, detail="Session not found")

    _col("session").update_one(
        {"_id": oid},
        {"$set": {"kyc": {"pan": pan.filename, "aadhaar": aadhaar.filename, "verified": True}, "stage": "underwriting"}},
    )

    msg = system_message("KYC verified successfully. What’s your monthly income?")
    _col("session").update_one({"_id": oid}, {"$push": {"messages": msg}})

    return {"ok": True, "message": msg}


@app.post("/api/sanction/generate/{session_id}")
def generate_sanction(session_id: str):
    oid = _oid(session_id)
    s = _col("session").find_one({"_id": oid})
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    offer = s.get("offer", {})
    name = s.get("customer_name", "Customer")
    letter = generate_offer_letter(name, offer)
    _col("session").update_one({"_id": oid}, {"$set": {"offer.letter": letter, "stage": "complete"}})
    return {"letter": letter}


# ---------- Business Docs ----------

def generate_offer_letter(name: str, offer: Dict[str, Any]) -> str:
    if not offer:
        return "No offer available."
    return (
        f"LoanLens AI – Sanction Letter\n\n"
        f"Date: {datetime.utcnow().date()}\n"
        f"To, {name}\n\n"
        f"We are pleased to sanction a personal loan with the following terms:\n"
        f"Approved Amount: ₹{offer.get('approved', 0):,}\n"
        f"Interest Rate: {offer.get('rate', 0)}% p.a.\n"
        f"Tenure: {offer.get('tenure_months', 0)} months\n"
        f"Processing Fee: ₹{offer.get('processing_fee', 0):,}\n\n"
        f"This is a system-generated letter and does not require a signature.\n"
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
