"""Application schema: users, roles, policies, sessions, audit, usage, caches, evaluation.

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    # ---- identity and authorization -------------------------------------------------------
    """
    CREATE TABLE app.roles (
        name TEXT PRIMARY KEY,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE app.role_policies (
        role TEXT PRIMARY KEY REFERENCES app.roles (name) ON DELETE CASCADE,
        allowed_tables TEXT[] NOT NULL DEFAULT '{}',
        allowed_columns JSONB NOT NULL DEFAULT '{}'::jsonb,
        row_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
        masked_columns JSONB NOT NULL DEFAULT '{}'::jsonb,
        max_rows INTEGER NOT NULL CHECK (max_rows BETWEEN 1 AND 100000),
        allow_sql_fallback BOOLEAN NOT NULL DEFAULT FALSE,
        version INTEGER NOT NULL DEFAULT 1,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE app.users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email TEXT NOT NULL,
        full_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL REFERENCES app.roles (name),
        scopes JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        failed_login_count INTEGER NOT NULL DEFAULT 0,
        locked_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX users_email_key ON app.users (lower(email))",
    """
    CREATE TABLE app.refresh_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
        family_id UUID NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        revoked_at TIMESTAMPTZ,
        replaced_by UUID,
        user_agent TEXT,
        client_ip TEXT
    )
    """,
    "CREATE INDEX refresh_tokens_family_idx ON app.refresh_tokens (family_id)",
    # ---- conversations and saved questions ------------------------------------------------
    """
    CREATE TABLE app.chat_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE app.chat_messages (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id UUID NOT NULL REFERENCES app.chat_sessions (id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE app.saved_queries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        question TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ---- audit (append only, hash chained) ------------------------------------------------
    """
    CREATE TABLE app.audit_log (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL,
        event TEXT NOT NULL,
        user_id UUID,
        role TEXT,
        session_id UUID,
        question TEXT,
        normalized_question TEXT,
        route TEXT,
        provider TEXT,
        model TEXT,
        prompt_version TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        plan_json JSONB,
        generated_sql TEXT,
        final_sql TEXT,
        validation_result JSONB,
        policy_hash TEXT,
        decision TEXT NOT NULL CHECK (decision IN ('allowed', 'denied', 'clarify', 'error', 'info')),
        denial_reason TEXT,
        row_count INTEGER,
        exec_ms INTEGER,
        total_ms INTEGER,
        is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
        client_ip TEXT,
        request_id TEXT,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL UNIQUE
    )
    """,
    "CREATE INDEX audit_log_ts_idx ON app.audit_log (ts)",
    "CREATE INDEX audit_log_user_idx ON app.audit_log (user_id, ts)",
    """
    CREATE FUNCTION app.forbid_audit_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'app.audit_log is append only';
    END;
    $$
    """,
    """
    CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON app.audit_log
    FOR EACH ROW EXECUTE FUNCTION app.forbid_audit_change()
    """,
    """
    CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON app.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_audit_change()
    """,
    # ---- usage, caches -------------------------------------------------------------------
    """
    CREATE TABLE app.llm_usage (
        id BIGSERIAL PRIMARY KEY,
        usage_date DATE NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        requests INTEGER NOT NULL DEFAULT 0,
        tokens_in BIGINT NOT NULL DEFAULT 0,
        tokens_out BIGINT NOT NULL DEFAULT 0,
        UNIQUE (usage_date, provider, model)
    )
    """,
    """
    CREATE TABLE app.query_cache (
        cache_key TEXT PRIMARY KEY,
        policy_hash TEXT NOT NULL,
        plan_json JSONB,
        generated_sql TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_hit_at TIMESTAMPTZ,
        hit_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE app.semantic_cache (
        id BIGSERIAL PRIMARY KEY,
        policy_hash TEXT NOT NULL,
        question TEXT NOT NULL,
        embedding VECTOR(384) NOT NULL,
        plan_json JSONB,
        generated_sql TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX semantic_cache_embedding_hnsw ON app.semantic_cache USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX semantic_cache_policy_idx ON app.semantic_cache (policy_hash)",
    # ---- semantic catalog index ----------------------------------------------------------
    """
    CREATE TABLE app.catalog_embeddings (
        id BIGSERIAL PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('metric', 'dimension', 'example')),
        name TEXT NOT NULL,
        content TEXT NOT NULL,
        model TEXT NOT NULL,
        embedding VECTOR(384) NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (kind, name)
    )
    """,
    "CREATE INDEX catalog_embeddings_hnsw ON app.catalog_embeddings USING hnsw (embedding vector_cosine_ops)",
    # ---- prompts and evaluation -----------------------------------------------------------
    """
    CREATE TABLE app.prompt_versions (
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (name, version)
    )
    """,
    """
    CREATE TABLE app.eval_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        suite TEXT NOT NULL,
        model TEXT,
        prompt_version TEXT,
        sample_size INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE app.eval_results (
        id BIGSERIAL PRIMARY KEY,
        run_id UUID NOT NULL REFERENCES app.eval_runs (id) ON DELETE CASCADE,
        question_id TEXT NOT NULL,
        passed BOOLEAN NOT NULL,
        route TEXT,
        generated_sql TEXT,
        error_class TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        latency_ms INTEGER,
        details JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
)

DOWNGRADE_TABLES: tuple[str, ...] = (
    "app.eval_results",
    "app.eval_runs",
    "app.prompt_versions",
    "app.catalog_embeddings",
    "app.semantic_cache",
    "app.query_cache",
    "app.llm_usage",
    "app.audit_log",
    "app.saved_queries",
    "app.chat_messages",
    "app.chat_sessions",
    "app.refresh_tokens",
    "app.users",
    "app.role_policies",
    "app.roles",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.forbid_audit_change()")
    for table in DOWNGRADE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
