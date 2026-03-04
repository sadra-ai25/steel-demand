import logging
from fastapi import FastAPI
import uvicorn

# --- وارد کردن کامپوننت‌ها از api.py
# main.py دیگر هیچ منطق اپلیکیشنی در خود ندارد.
from app.api import router, create_startup_handler, create_shutdown_handler

# تنظیم لاگ‌گیری
logging.basicConfig(level=logging.INFO)

# --- ایجاد اپلیکیشن ---
# این خط یکی از اولین دستوراتی است که اجرا می‌شود و تضمین می‌کند uvicorn آن را پیدا کند.
app = FastAPI(title="Steel Ingot Analysis API", version="1.0.0")

# --- اتصال رویدادهای Startup و Shutdown ---
# توابع کمکی، خودِ "handler" را برای ما ایجاد می‌کنند.
app.on_event("startup")(create_startup_handler(app))
app.on_event("shutdown")(create_shutdown_handler(app))

# --- اتصال روتر ---
app.include_router(router)

# این بخش فقط برای اجرای مستقیم فایل است و در داکر استفاده نمی‌شود.
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001, reload=True)