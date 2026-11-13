-- Target schema for the reference customer-success app (Postgres).
-- Kept in step with schema.py; tests/test_target.py checks the two agree on tables and fields.

CREATE TABLE accounts (
    id              bigserial PRIMARY KEY,
    tenant_id       uuid NOT NULL,
    external_id     text NOT NULL,
    name            text NOT NULL,
    industry        text,
    tier            text CHECK (tier IN ('free', 'standard', 'enterprise')),
    website         text,
    customer_since  date,
    owner_email     text,
    UNIQUE (tenant_id, external_id)
);

CREATE TABLE contacts (
    id                   bigserial PRIMARY KEY,
    tenant_id            uuid NOT NULL,
    external_id          text NOT NULL,
    account_external_id  text NOT NULL,
    first_name           text,
    last_name            text NOT NULL,
    email                text NOT NULL,
    phone                text,
    role                 text CHECK (role IN
                           ('decision_maker', 'champion', 'billing', 'technical', 'other')),
    UNIQUE (tenant_id, external_id)
);

CREATE TABLE deals (
    id                   bigserial PRIMARY KEY,
    tenant_id            uuid NOT NULL,
    external_id          text NOT NULL,
    account_external_id  text NOT NULL,
    name                 text NOT NULL,
    amount               numeric(18, 2) NOT NULL,
    currency             text NOT NULL DEFAULT 'USD',
    stage                text NOT NULL CHECK (stage IN
                           ('lead', 'qualified', 'proposal', 'negotiation',
                            'closed_won', 'closed_lost')),
    close_date           date,
    owner_email          text,
    UNIQUE (tenant_id, external_id)
);

CREATE TABLE activities (
    id                   bigserial PRIMARY KEY,
    tenant_id            uuid NOT NULL,
    external_id          text NOT NULL,
    related_type         text NOT NULL CHECK (related_type IN ('account', 'deal')),
    related_external_id  text NOT NULL,
    kind                 text NOT NULL CHECK (kind IN ('call', 'email', 'meeting', 'task')),
    subject              text NOT NULL,
    occurred_at          timestamptz NOT NULL,
    notes                text,
    UNIQUE (tenant_id, external_id)
);
