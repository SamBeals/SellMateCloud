from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uuid
from datetime import datetime, timezone

from google.cloud import firestore

app = FastAPI()
db = firestore.Client()

@app.get("/health")
def health():
    return {"status": "ok"}

class OrderItem(BaseModel):
    slot_id: str
    qty: int

class CreateOrderRequest(BaseModel):
    machine_id: str
    items: List[OrderItem]
    amount_cents: int

@app.post("/orders")
def create_order(req: CreateOrderRequest):
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    doc = {
        "order_id": order_id,
        "machine_id": req.machine_id,
        "items": [i.model_dump() for i in req.items],
        "amount_cents": req.amount_cents,
        "status": "CREATED",
        "created_at": now,
        "updated_at": now,
    }

    db.collection("orders").document(order_id).set(doc)

    return {
        **doc,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    snap = db.collection("orders").document(order_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    data = snap.to_dict() or {}
    for k in ["created_at", "updated_at"]:
        v = data.get(k)
        if hasattr(v, "isoformat"):
            data[k] = v.isoformat()

    return data
