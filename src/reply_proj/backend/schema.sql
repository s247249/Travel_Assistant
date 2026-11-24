-- Travel RAG assistant — business database (SQLite)
-- Design: docs/architecture.md (D2, D8-D13). Facts & constraints only;
-- semantic descriptions live in Chroma and join via shared entity IDs.
PRAGMA foreign_keys = ON;

-- ============ Identity & geography ============

CREATE TABLE IF NOT EXISTS airports (
    code    TEXT PRIMARY KEY,              -- IATA, e.g. 'TRN'
    city    TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cities (
    id           TEXT PRIMARY KEY,         -- slug, e.g. 'rome'
    name         TEXT NOT NULL,
    country      TEXT NOT NULL,
    airport_code TEXT NOT NULL REFERENCES airports(code),
    cost_index   REAL NOT NULL,            -- price-band multiplier (D10)
    tags         TEXT NOT NULL DEFAULT '[]'  -- JSON list, e.g. ["sea","food","niche"]
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name          TEXT,
    home_airport  TEXT REFERENCES airports(code),  -- default origin, overridable in chat (D8)
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Inventory ============

CREATE TABLE IF NOT EXISTS hotels (
    id                  TEXT PRIMARY KEY,  -- 'hotel_naples_003' == corpus document id
    city_id             TEXT NOT NULL REFERENCES cities(id),
    name                TEXT NOT NULL,
    tier                TEXT NOT NULL CHECK (tier IN ('budget','mid','high')),
    max_guests_per_room INTEGER NOT NULL CHECK (max_guests_per_room >= 1),
    amenities           TEXT NOT NULL DEFAULT '[]'   -- JSON list, e.g. ["pool","breakfast"]
);

CREATE TABLE IF NOT EXISTS hotel_availability (
    hotel_id    TEXT NOT NULL REFERENCES hotels(id),
    date        TEXT NOT NULL,             -- ISO 'YYYY-MM-DD'
    rooms_left  INTEGER NOT NULL CHECK (rooms_left >= 0),
    price_night REAL NOT NULL CHECK (price_night > 0),  -- per room, this specific night (S3)
    PRIMARY KEY (hotel_id, date)
);

CREATE TABLE IF NOT EXISTS activities (
    id           TEXT PRIMARY KEY,         -- 'activity_rome_007' == corpus document id
    city_id      TEXT NOT NULL REFERENCES cities(id),
    name         TEXT NOT NULL,
    category     TEXT NOT NULL CHECK (category IN ('culture','sport','relax','nightlife','food','nature')),
    duration_min INTEGER NOT NULL CHECK (duration_min > 0),
    base_price   REAL NOT NULL CHECK (base_price >= 0),  -- per person; 0 = free
    targets      TEXT NOT NULL DEFAULT '[]'  -- JSON list; authority = generator (D24/F4 amended)
);

CREATE TABLE IF NOT EXISTS activity_availability (
    activity_id TEXT NOT NULL REFERENCES activities(id),
    date        TEXT NOT NULL,
    spots_left  INTEGER NOT NULL CHECK (spots_left >= 0),
    PRIMARY KEY (activity_id, date)
);

CREATE TABLE IF NOT EXISTS flights (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_code   TEXT NOT NULL REFERENCES airports(code),
    to_code     TEXT NOT NULL REFERENCES airports(code),
    date        TEXT NOT NULL,
    depart_time TEXT NOT NULL,             -- 'HH:MM'
    price       REAL NOT NULL CHECK (price > 0),        -- per seat
    seats_left  INTEGER NOT NULL CHECK (seats_left >= 0),
    CHECK (from_code <> to_code),          -- no self-flights (Rome origin -> Rome destination)
    UNIQUE (from_code, to_code, date, depart_time)
);

-- ============ Conversation index (S2 discussion) ============
-- LangGraph's checkpointer (separate checkpoints.db) stores full state per thread;
-- this table only indexes threads per user so the UI can list conversations.

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,           -- == LangGraph thread_id (UUID)
    user_id    INTEGER NOT NULL REFERENCES users(id),
    title      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Commerce ============

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    proposal_id    TEXT UNIQUE,            -- idempotency: one booking per proposal (S2)
    status         TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed','cancelled')),
    city_id        TEXT NOT NULL REFERENCES cities(id),
    origin_airport TEXT NOT NULL REFERENCES airports(code),
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    n_travelers    INTEGER NOT NULL CHECK (n_travelers >= 1),
    total_price    REAL NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (end_date > start_date)
);

CREATE TABLE IF NOT EXISTS booking_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    item_type  TEXT NOT NULL CHECK (item_type IN ('flight','hotel_night','activity')),
    ref_id     TEXT NOT NULL,              -- flights.id / hotels.id / activities.id
    date       TEXT NOT NULL,              -- hotel: one row per night (S1)
    quantity   INTEGER NOT NULL CHECK (quantity >= 1),  -- seats / rooms / spots
    unit_price REAL NOT NULL,
    subtotal   REAL NOT NULL
);

-- ============ Indexes (hot query paths) ============

CREATE INDEX IF NOT EXISTS idx_flights_route_date   ON flights(from_code, to_code, date);
CREATE INDEX IF NOT EXISTS idx_hotel_avail_date     ON hotel_availability(date);
CREATE INDEX IF NOT EXISTS idx_activity_avail_date  ON activity_availability(date);
CREATE INDEX IF NOT EXISTS idx_booking_items_booking ON booking_items(booking_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user   ON conversations(user_id);
