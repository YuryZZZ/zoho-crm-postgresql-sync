-- PARL Tables for OpenCode TaskBus
-- ===================================
-- Adds support for Parallel-Agent Reinforcement Learning
-- Run: psql -U postgres -d opencode_taskbus -f parl_tables.sql

-- Critical Steps Tracking (PARL latency metric)
CREATE TABLE IF NOT EXISTS critical_steps (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_number INT NOT NULL,
    orchestrator_steps INT DEFAULT 0,
    max_subagent_steps INT DEFAULT 0,
    critical_step_total INT GENERATED ALWAYS AS (orchestrator_steps + max_subagent_steps) STORED,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_critical_steps_run FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_critical_steps_run ON critical_steps(run_id);

-- Subagent Sessions (PARL session isolation)
CREATE TABLE IF NOT EXISTS subagent_sessions (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    subagent_id VARCHAR(64) NOT NULL,
    parent_session_id INT,  -- For nested subagents
    model VARCHAR(128),
    profile VARCHAR(64),    -- vision, docs, coder, architect, explorer, memory
    spawned_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) DEFAULT 'active',  -- spawning, active, completed, failed, cancelled
    context_tokens INT DEFAULT 0,
    steps_executed INT DEFAULT 0,
    result JSONB,
    error_message TEXT,
    UNIQUE(run_id, subagent_id),
    CONSTRAINT fk_subagent_run FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_subagent_parent FOREIGN KEY (parent_session_id) REFERENCES subagent_sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_subagent_run ON subagent_sessions(run_id);
CREATE INDEX IF NOT EXISTS idx_subagent_status ON subagent_sessions(status);

-- Parallel Execution Graph (DAG of task dependencies)
CREATE TABLE IF NOT EXISTS execution_graph (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_task_id TEXT,            -- NULL for root tasks
    child_task_id TEXT NOT NULL,
    dependency_type VARCHAR(32),    -- 'parallel', 'sequential', 'aggregate', 'conditional'
    condition JSONB,                -- For conditional dependencies
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_graph_run FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_graph_parent FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id) ON DELETE SET NULL,
    CONSTRAINT fk_graph_child FOREIGN KEY (child_task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_graph_run ON execution_graph(run_id);
CREATE INDEX IF NOT EXISTS idx_graph_parent ON execution_graph(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_graph_child ON execution_graph(child_task_id);

-- PARL Reward Tracking (for optimization analytics)
CREATE TABLE IF NOT EXISTS parl_rewards (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    training_step INT DEFAULT 0,
    reward DECIMAL(10, 6),
    lambda_aux DECIMAL(10, 6),
    r_parallel DECIMAL(10, 6),
    success_indicator DECIMAL(10, 6),
    q_tau DECIMAL(10, 6),
    num_subagents INT,
    critical_steps INT,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_reward_run FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rewards_run ON parl_rewards(run_id);

-- Task Decomposition Cache (for repeated similar tasks)
CREATE TABLE IF NOT EXISTS decomposition_cache (
    id SERIAL PRIMARY KEY,
    task_hash VARCHAR(64) NOT NULL,  -- MD5 of task description
    task_description TEXT NOT NULL,
    decomposition JSONB NOT NULL,    -- Cached subtask breakdown
    success_rate DECIMAL(5, 4) DEFAULT 0.0,
    usage_count INT DEFAULT 1,
    avg_critical_steps DECIMAL(10, 2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(task_hash)
);

CREATE INDEX IF NOT EXISTS idx_decomp_hash ON decomposition_cache(task_hash);
CREATE INDEX IF NOT EXISTS idx_decomp_success ON decomposition_cache(success_rate DESC);

-- Views for PARL Analytics
CREATE OR REPLACE VIEW parl_run_summary AS
SELECT
    r.run_id,
    r.status,
    r.created_at,
    r.updated_at,
    COUNT(DISTINCT ss.id) AS total_subagents,
    COUNT(DISTINCT ss.id) FILTER (WHERE ss.status = 'completed') AS completed_subagents,
    MAX(cs.critical_step_total) AS max_critical_steps,
    AVG(cs.critical_step_total) AS avg_critical_steps,
    SUM(ss.steps_executed) AS total_steps_executed,
    MAX(pr.reward) AS final_reward
FROM runs r
LEFT JOIN subagent_sessions ss ON r.run_id = ss.run_id
LEFT JOIN critical_steps cs ON r.run_id = cs.run_id
LEFT JOIN parl_rewards pr ON r.run_id = pr.run_id
GROUP BY r.run_id, r.status, r.created_at, r.updated_at;

-- Function: Get optimal decomposition for similar task
CREATE OR REPLACE FUNCTION get_cached_decomposition(p_task_description TEXT)
RETURNS JSONB AS $$
DECLARE
    v_hash VARCHAR(64);
    v_decomposition JSONB;
BEGIN
    v_hash := md5(lower(trim(p_task_description)));

    SELECT decomposition INTO v_decomposition
    FROM decomposition_cache
    WHERE task_hash = v_hash
      AND success_rate > 0.7
    ORDER BY success_rate DESC, usage_count DESC
    LIMIT 1;

    IF v_decomposition IS NOT NULL THEN
        UPDATE decomposition_cache
        SET usage_count = usage_count + 1,
            last_used_at = NOW()
        WHERE task_hash = v_hash;
    END IF;

    RETURN v_decomposition;
END;
$$ LANGUAGE plpgsql;

-- Function: Calculate critical path length
CREATE OR REPLACE FUNCTION calculate_critical_path(p_run_id TEXT)
RETURNS INT AS $$
DECLARE
    v_critical_path INT;
BEGIN
    WITH RECURSIVE path AS (
        -- Start with root tasks (no parent)
        SELECT
            eg.child_task_id,
            1 AS depth,
            ARRAY[eg.child_task_id] AS path
        FROM execution_graph eg
        WHERE eg.run_id = p_run_id
          AND eg.parent_task_id IS NULL

        UNION ALL

        -- Follow dependencies
        SELECT
            eg.child_task_id,
            p.depth + 1,
            p.path || eg.child_task_id
        FROM execution_graph eg
        JOIN path p ON eg.parent_task_id = p.child_task_id
        WHERE eg.run_id = p_run_id
          AND NOT eg.child_task_id = ANY(p.path)  -- Prevent cycles
    )
    SELECT MAX(depth) INTO v_critical_path FROM path;

    RETURN COALESCE(v_critical_path, 0);
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON critical_steps TO postgres;
GRANT ALL ON subagent_sessions TO postgres;
GRANT ALL ON execution_graph TO postgres;
GRANT ALL ON parl_rewards TO postgres;
GRANT ALL ON decomposition_cache TO postgres;
GRANT SELECT ON parl_run_summary TO postgres;

-- Done
SELECT 'PARL tables created successfully' AS status;
