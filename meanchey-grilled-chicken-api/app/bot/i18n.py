from app.models import Language

TEXTS: dict[str, dict[Language, str]] = {
    "start": {
        Language.KM: (
            "សួស្តី {name}! 👋\n"
            "សូមស្វាគមន៍មកកាន់ <b>មាន់អាំងមានជ័យ</b>។\n"
            "ចុចប៊ូតុងខាងក្រោមដើម្បីបើកកម្មវិធី។\n\n"
            "<i>Hello! Type /lang to switch to English.</i>"
        ),
        Language.EN: (
            "Hello {name}! 👋\n"
            "Welcome to <b>Mean Chey Grilled Chicken</b>.\n"
            "Tap the button below to open the app.\n\n"
            "<i>សួស្តី! វាយ /lang ដើម្បីប្តូរទៅភាសាខ្មែរ។</i>"
        ),
    },
    "open_app": {
        Language.KM: "🍗 បើកកម្មវិធី",
        Language.EN: "🍗 Open app",
    },
    "lang_changed": {
        Language.KM: "✅ បានប្តូរភាសាទៅជាភាសាខ្មែរ។",
        Language.EN: "✅ Language switched to English.",
    },
    "app_unavailable": {
        Language.KM: "⚠️ កម្មវិធីមិនទាន់បានកំណត់នៅឡើយទេ។ សូមទាក់ទងអ្នកគ្រប់គ្រង។",
        Language.EN: "⚠️ The app is not configured yet. Please contact an administrator.",
    },
    # --- Production alerts (app/bot/notify.py). {again} is empty or " again" for a repeat. ---
    "again": {
        Language.KM: " ម្តងទៀត",
        Language.EN: " again",
    },
    "processing_finished": {
        Language.KM: (
            "✅ <b>{code}</b>៖ ការផលិតបានបញ្ចប់{again} — មាន់ {quantity} ក្បាល → ស្លាប {wings} "
            "ភ្លៅ {thighs}។ សូមកំណត់ផែនការវេចខ្ចប់។"
        ),
        Language.EN: (
            "✅ <b>{code}</b>: processing finished{again} — {quantity} chickens → {wings} wings, "
            "{thighs} thighs. Set the packaging plan."
        ),
    },
    "completed_as_planned": {
        Language.KM: (
            "🎉 <b>{code}</b>៖ ផលិតកម្មបានបញ្ចប់{again} ស្របតាមផែនការ — កញ្ចប់ ៤ ដុំ {big} "
            "និងកញ្ចប់ ២ ដុំ {small}។"
        ),
        Language.EN: (
            "🎉 <b>{code}</b>: production completed{again} as planned — {big} × 4-Piece Packs, "
            "{small} × 2-Piece Packs."
        ),
    },
    "completed_differs": {
        Language.KM: (
            "⚠️ <b>{code}</b>៖ ផលិតកម្មបានបញ្ចប់{again} ខុសពីផែនការ។ ផែនការ {pb} / {ps} "
            "ជាក់ស្តែង {ab} / {as_}។ មតិយោបល់៖ “{comment}”។"
        ),
        Language.EN: (
            "⚠️ <b>{code}</b>: production completed{again}, different from the plan. "
            "Planned {pb} / {ps}, actual {ab} / {as_}. Comment: “{comment}”."
        ),
    },
    "open_plan": {
        Language.KM: "📋 បើកផែនការ",
        Language.EN: "📋 Open plan",
    },
    "open_batch": {
        Language.KM: "🍗 បើកផលិតកម្ម",
        Language.EN: "🍗 Open batch",
    },
    # --- Order alerts (app/bot/notify.py) ---
    "order_delivering": {
        Language.KM: (
            "🚚 <b>{code}</b> សម្រាប់ {customer} កំពុងដឹកជញ្ជូន — ប្រអប់ស {white} / ប្រអប់ខ្មៅ {black}។"
        ),
        Language.EN: (
            "🚚 <b>{code}</b> for {customer} is out for delivery — {white} white / {black} black "
            "boxes."
        ),
    },
    "order_delivered": {
        Language.KM: "✅ <b>{code}</b>៖ បានដឹកដល់ {customer} អតិថិជនទទួលយកទាំងអស់។",
        Language.EN: "✅ <b>{code}</b>: delivered to {customer}, everything accepted.",
    },
    "order_return_pending": {
        Language.KM: (
            "↩️ <b>{code}</b>៖ {customer} បានប្រគល់ទំនិញមកវិញ — {summary}។ មូលហេតុ៖ “{reason}”។ "
            "សូមពិនិត្យទំនិញប្រគល់មកវិញ។"
        ),
        Language.EN: (
            "↩️ <b>{code}</b>: {customer} returned items — {summary}. Reason: “{reason}”. "
            "Review the return."
        ),
    },
    "order_returns_reviewed": {
        Language.KM: (
            "📦 <b>{code}</b>៖ បានពិនិត្យទំនិញប្រគល់មកវិញ — {outcome} (ចូលស្តុក {to_stock}, "
            "ខូចខាត {to_wasted})។"
        ),
        Language.EN: (
            "📦 <b>{code}</b>: return reviewed — {outcome} ({to_stock} to stock, "
            "{to_wasted} wasted)."
        ),
    },
    "order_partly_returned": {
        Language.KM: "ប្រគល់មកវិញខ្លះ",
        Language.EN: "partly returned",
    },
    "order_fully_returned": {
        Language.KM: "ប្រគល់មកវិញទាំងអស់",
        Language.EN: "fully returned",
    },
    "order_item_count": {
        Language.KM: "{name} {count}",
        Language.EN: "{count} × {name}",
    },
    "order_item_kg": {
        Language.KM: "{name} {kg} គ.ក",
        Language.EN: "{kg} kg {name}",
    },
    "order_nothing": {
        Language.KM: "គ្មាន",
        Language.EN: "nothing",
    },
    "open_order": {
        Language.KM: "🧾 បើកការបញ្ជាទិញ",
        Language.EN: "🧾 Open order",
    },
    # --- Superadmin Telegram linking (/start link_<token>) ---
    "link_done": {
        Language.KM: "✅ បានភ្ជាប់ Telegram រួចរាល់។",
        Language.EN: "✅ Telegram linked.",
    },
    "link_invalid": {
        Language.KM: "⚠️ តំណនេះមិនអាចប្រើបានទេ។ សូមបង្កើតតំណថ្មីក្នុងកម្មវិធី។",
        Language.EN: "⚠️ This link can't be used. Create a new one in the app.",
    },
}


def t(lang: Language, key: str, **kwargs: object) -> str:
    return TEXTS[key][lang].format(**kwargs)
