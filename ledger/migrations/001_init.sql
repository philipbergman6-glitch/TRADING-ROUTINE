-- Ledger schema: the immutable record of every order's lifecycle.
--
-- Design intent: this is a LEDGER, not a log table with a JSON blob in it.
-- The order lifecycle is modelled with real tables, real foreign keys and real
-- check constraints, so that an impossible state is impossible to store rather
-- than merely unlikely to be written.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- orders: one row per *proposed* order, whether or not it was ever submitted.
-- Refused orders are recorded too -- an audit trail that only contains the
-- orders that succeeded answers none of the interesting questions.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
    id                UUID PRIMARY KEY,

    -- Duplicate-order prevention. The caller derives this from the trade's
    -- identity (symbol + qty + side + session), so a retry after a network
    -- timeout collides here instead of buying twice.
    idempotency_key   TEXT        NOT NULL UNIQUE,

    symbol            TEXT        NOT NULL CHECK (symbol = upper(symbol) AND length(symbol) > 0),
    side              TEXT        NOT NULL CHECK (side IN ('buy', 'sell')),
    qty               NUMERIC(18, 8) NOT NULL CHECK (qty > 0),
    price             NUMERIC(18, 8) NOT NULL CHECK (price > 0),
    stop_price        NUMERIC(18, 8) CHECK (stop_price IS NULL OR stop_price > 0),
    trail_percent     NUMERIC(8, 4)  CHECK (trail_percent IS NULL OR trail_percent > 0),

    -- Provenance: which rulebook version allowed this, and what research
    -- justified it. Without these the ledger cannot answer "why did this
    -- order exist".
    strategy_version  TEXT        NOT NULL,
    research_ref      TEXT,

    status            TEXT        NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed', 'refused', 'submitted', 'filled', 'rejected', 'cancelled')),
    broker_order_id   TEXT,

    proposed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at      TIMESTAMPTZ,
    filled_at         TIMESTAMPTZ,

    -- A submitted order must have a broker id; a filled order must have a fill
    -- time. Enforced here rather than hoped for in application code.
    CONSTRAINT submitted_has_broker_id
        CHECK (status NOT IN ('submitted', 'filled') OR broker_order_id IS NOT NULL),
    CONSTRAINT filled_has_timestamp
        CHECK (status <> 'filled' OR filled_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS orders_symbol_proposed_at_idx ON orders (symbol, proposed_at DESC);
CREATE INDEX IF NOT EXISTS orders_status_idx ON orders (status);

-- ---------------------------------------------------------------------------
-- validations: the risk engine's verdict on an order. One per order.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS validations (
    id            UUID PRIMARY KEY,
    order_id      UUID        NOT NULL UNIQUE REFERENCES orders (id) ON DELETE CASCADE,
    approved      BOOLEAN     NOT NULL,
    engine_version TEXT       NOT NULL,
    decided_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each rule the order broke, one row each -- so "which rule refuses most
-- often" is a GROUP BY, not a text search through a blob.
CREATE TABLE IF NOT EXISTS validation_violations (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    validation_id  UUID NOT NULL REFERENCES validations (id) ON DELETE CASCADE,
    rule           TEXT NOT NULL,
    detail         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS validation_violations_rule_idx ON validation_violations (rule);

-- ---------------------------------------------------------------------------
-- broker_responses: exactly what Alpaca said, kept verbatim.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS broker_responses (
    id           UUID PRIMARY KEY,
    order_id     UUID        NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    kind         TEXT        NOT NULL CHECK (kind IN ('submit', 'stop', 'cancel', 'poll')),
    http_status  INTEGER,
    payload      JSONB       NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS broker_responses_order_idx ON broker_responses (order_id, received_at);

-- ---------------------------------------------------------------------------
-- audit_events: append-only. Enforced by trigger, not by convention.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_events (
    id           UUID PRIMARY KEY,
    order_id     UUID REFERENCES orders (id) ON DELETE RESTRICT,
    event_type   TEXT        NOT NULL,
    payload      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_events_order_idx ON audit_events (order_id, occurred_at);

CREATE OR REPLACE FUNCTION refuse_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % refused', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION refuse_mutation();

INSERT INTO schema_migrations (version) VALUES ('001_init')
    ON CONFLICT (version) DO NOTHING;
