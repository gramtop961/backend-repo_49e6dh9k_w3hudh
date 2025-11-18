from fastapi import FastAPI, HTTPException, Depends, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime
import uuid
import os
import stripe

# In-memory store for demo (replace with MongoDB in production)
DB: Dict[str, Any] = {
    "products": [],
    "orders": {},
    "customers": {},
    "coupons": {},
    "settings": {
        "payment": {
            "stripe_public": "",
            "stripe_secret": "",
            "paypal_client": "",
            "paypal_secret": "",
            "klarna_merchant": "",
            "klarna_secret": "",
        },
        "analytics": {
            "ga4_measurement_id": "",
            "facebook_pixel_id": "",
            "mailchimp_api_key": ""
        },
        "shipping": {
            "zones": {
                "SE": {"name": "Sverige", "rate": 49, "free_over": 800},
                "EU": {"name": "EU", "rate": 99, "free_over": 1200},
                "WORLD": {"name": "Resten av världen", "rate": 149, "free_over": 2000}
            }
        },
        "tax": {
            "SE": 0.25
        }
    }
}

app = FastAPI(title="Bambu & Co API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Variant(BaseModel):
    option_name: str
    option_values: List[str] = []
    sku: Optional[str] = None
    price: Optional[float] = None
    inventory: int = 0


class Product(BaseModel):
    id: Optional[str] = None
    title: str
    slug: str
    category: str
    short_description: str
    long_description: str
    price: float
    compare_at_price: Optional[float] = None
    SKU: str
    inventory_quantity: int
    inventory_policy: Literal['continue', 'deny'] = 'deny'
    weight: Optional[float] = None
    dimensions: Optional[str] = None
    variants: List[Variant] = []
    images: List[str] = []
    tags: List[str] = []
    material: Optional[str] = None
    care_instructions: Optional[str] = None
    shipping_class: Optional[str] = None
    tax_class: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    created_at: Optional[datetime] = None


class Customer(BaseModel):
    id: Optional[str] = None
    name: str
    email: EmailStr
    addresses: List[Dict[str, Any]] = []
    order_history: List[str] = []


class LineItem(BaseModel):
    product_id: str
    sku: Optional[str] = None
    qty: int
    price: float


class Address(BaseModel):
    first_name: str
    last_name: str
    address1: str
    address2: Optional[str] = None
    postal_code: str
    city: str
    country: str


class Order(BaseModel):
    id: Optional[str] = None
    order_number: Optional[str] = None
    status: Literal['pending', 'paid', 'fulfilled', 'cancelled'] = 'pending'
    customer: Optional[str] = None
    line_items: List[LineItem]
    totals: Dict[str, float]
    shipping_address: Address
    billing_address: Address
    payment_info: Dict[str, Any] = {}
    created_at: Optional[datetime] = None


class Coupon(BaseModel):
    code: str
    type: Literal['fixed', 'percent']
    value: float
    valid_from: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = None


class Settings(BaseModel):
    payment: Dict[str, str]
    analytics: Dict[str, str]
    shipping: Dict[str, Any]
    tax: Dict[str, float]


@app.get("/test")
def test():
    return {"status": "ok", "message": "Bambu & Co API running"}


@app.get("/products", response_model=List[Product])
def list_products(
    q: Optional[str] = Query(None),
    category: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    material: Optional[str] = None,
    sort: Optional[str] = Query(None, description="bestseller|new|price_asc|price_desc"),
    limit: int = 50,
    offset: int = 0,
):
    products = DB["products"]
    results: List[Product] = []
    for p in products:
        if q and q.lower() not in (p.title + p.short_description + p.long_description).lower():
            continue
        if category and p.category != category:
            continue
        if material and (p.material or '').lower().find(material.lower()) == -1:
            continue
        # simple price filter
        base_price = p.price
        if price_min is not None and base_price < price_min:
            continue
        if price_max is not None and base_price > price_max:
            continue
        results.append(p)
    if sort == 'price_asc':
        results.sort(key=lambda x: x.price)
    elif sort == 'price_desc':
        results.sort(key=lambda x: x.price, reverse=True)
    elif sort == 'new':
        results.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    # bestseller sort placeholder: keep as-is
    return results[offset: offset + limit]


@app.get("/products/{product_id}", response_model=Product)
def get_product(product_id: str):
    for p in DB["products"]:
        if p.id == product_id or p.slug == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")


@app.post("/products", response_model=Product)
def create_product(product: Product):
    product.id = str(uuid.uuid4())
    product.created_at = datetime.utcnow()
    DB["products"].append(product)
    return product


@app.put("/products/{product_id}", response_model=Product)
def update_product(product_id: str, product: Product):
    for idx, p in enumerate(DB["products"]):
        if p.id == product_id or p.slug == product_id:
            # preserve id/created_at
            product.id = p.id
            product.created_at = p.created_at
            DB["products"][idx] = product
            return product
    raise HTTPException(status_code=404, detail="Product not found")


@app.delete("/products/{product_id}")
def delete_product(product_id: str):
    for idx, p in enumerate(DB["products"]):
        if p.id == product_id or p.slug == product_id:
            del DB["products"][idx]
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Product not found")


@app.post("/orders", response_model=Order)
def create_order(order: Order):
    order.id = str(uuid.uuid4())
    order.order_number = f"BAM-{int(datetime.utcnow().timestamp())}"
    order.created_at = datetime.utcnow()
    DB["orders"][order.id] = order.model_dump()
    return order


@app.get("/orders", response_model=List[Order])
def list_orders(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    orders = list(DB["orders"].values())
    if status:
        orders = [o for o in orders if o.get("status") == status]
    # sort newest first by created_at
    orders.sort(key=lambda o: o.get("created_at", datetime.min), reverse=True)
    return orders[offset: offset + limit]


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    if order_id in DB["orders"]:
        return DB["orders"][order_id]
    raise HTTPException(status_code=404, detail="Order not found")


@app.post("/customers", response_model=Customer)
def create_customer(customer: Customer):
    customer.id = str(uuid.uuid4())
    DB["customers"][customer.id] = customer.model_dump()
    return customer


@app.get("/settings", response_model=Settings)
def get_settings():
    return DB["settings"]


@app.put("/settings", response_model=Settings)
def update_settings(settings: Settings):
    DB["settings"] = settings.model_dump()
    return DB["settings"]


# Payments: Stripe Checkout (test-mode)
class CheckoutRequest(BaseModel):
    line_items: List[LineItem]
    totals: Dict[str, float]
    shipping_address: Address
    billing_address: Address
    locale: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@app.post("/payments/stripe/checkout")
def create_stripe_checkout(payload: CheckoutRequest):
    # Create a pending order first
    order = Order(
        line_items=payload.line_items,
        totals=payload.totals,
        shipping_address=payload.shipping_address,
        billing_address=payload.billing_address,
        payment_info={"method": "stripe", "status": "pending"},
    )
    created = create_order(order)  # reuse existing creator

    # Configure Stripe
    secret = DB["settings"]["payment"].get("stripe_secret") or os.getenv("STRIPE_SECRET", "")
    if not secret:
        raise HTTPException(status_code=400, detail="Stripe not configured")
    stripe.api_key = secret

    # Build Stripe line items (amount in öre)
    stripe_items = []
    for li in payload.line_items:
        # Try to fetch product title for display
        title = li.sku or li.product_id
        for p in DB["products"]:
            if p.id == li.product_id or p.SKU == li.sku:
                title = p.title
                break
        stripe_items.append({
            "price_data": {
                "currency": "sek",
                "product_data": {"name": title},
                "unit_amount": int(round(li.price * 100)),
            },
            "quantity": li.qty,
        })

    success_url = payload.success_url or "https://example.com/checkout/success"
    cancel_url = payload.cancel_url or "https://example.com/checkout/cancel"

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=stripe_items,
        success_url=f"{success_url}?order_id={created.id}",
        cancel_url=cancel_url,
        metadata={"order_id": created.id},
        locale=(payload.locale or "sv"),
    )

    # Attach session id to order
    DB["orders"][created.id]["payment_info"].update({
        "stripe_session_id": session.id
    })

    return {"url": session.url, "order_id": created.id}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    if not endpoint_secret:
        # If no secret configured, skip verification for demo
        try:
            event = stripe.Event.construct_from(request.json(), stripe.api_key)
        except Exception:
            # Fallback parse
            event = None
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload, sig_header=sig, secret=endpoint_secret
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    if event and event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id and order_id in DB["orders"]:
            DB["orders"][order_id]["status"] = "paid"
            DB["orders"][order_id]["payment_info"]["status"] = "paid"
            DB["orders"][order_id]["payment_info"]["stripe_session_id"] = session.get("id")

    return {"received": True}


# Seed demo products
if not DB["products"]:
    demo_products = [
        Product(
            id=str(uuid.uuid4()),
            title="Bambu T-shirt — Classic",
            slug="bambu-tshirt-classic",
            category="T-shirt",
            short_description="Mjukt och temperaturreglerande tyg av 95% bambuviskos. Perfekt för vardag.",
            long_description="Detaljerad beskrivning, material, tvättråd och ursprung.",
            price=349,
            compare_at_price=None,
            SKU="BMT-TSH-001",
            inventory_quantity=120,
            variants=[
                Variant(option_name="Storlek", option_values=["S", "M", "L", "XL"], inventory=120),
                Variant(option_name="Färg", option_values=["Naturvit", "Mörkgrön"], inventory=120),
            ],
            images=["/images/products/bamboo-tshirt-classic-1.webp"],
            tags=["bestseller"],
            material="95% bambuviskos, 5% elastan",
            care_instructions="Maskintvätt 30°C",
            shipping_class="standard",
            tax_class="SE25",
            seo_title="Bambu T-shirt Classic — Bambu & Co",
            seo_description="Mjuk bambutshirt, ekologisk och hållbar. Fri frakt över 800 kr.",
            created_at=datetime.utcnow(),
        ),
        Product(
            id=str(uuid.uuid4()),
            title="Bambu Underställ — Merino-blend",
            slug="bambu-understall-merino",
            category="Underkläder",
            short_description="Värmande lager i bambu/merinoblandning.",
            long_description="Detaljerad beskrivning.",
            price=499,
            SKU="BMT-UND-002",
            inventory_quantity=80,
            variants=[Variant(option_name="Storlek", option_values=["S", "M", "L"], inventory=80)],
            images=["/images/products/bamboo-base-merino.webp"],
            tags=["nyhet"],
            material="Bambu & merino",
            care_instructions="Maskintvätt 30°C",
            shipping_class="standard",
            tax_class="SE25",
            created_at=datetime.utcnow(),
        ),
        Product(
            id=str(uuid.uuid4()),
            title="Bambu Tröja — Oversized",
            slug="bambu-troja-oversized",
            category="Tröja",
            short_description="Rymlig och bekväm tröja i bambu.",
            long_description="Detaljerad beskrivning.",
            price=699,
            SKU="BMT-TRJ-003",
            inventory_quantity=50,
            variants=[Variant(option_name="Storlek", option_values=["S", "M", "L", "XL"], inventory=50)],
            images=["/images/products/bamboo-sweater-oversized.webp"],
            tags=[""],
            material="Bambuviskos",
            care_instructions="Maskintvätt 30°C",
            shipping_class="standard",
            tax_class="SE25",
            created_at=datetime.utcnow(),
        ),
    ]
    DB["products"].extend(demo_products)
