-- Read-only role for the agent. Even if the LLM generates a bad or
-- malicious query, this role physically cannot INSERT/UPDATE/DELETE.
CREATE ROLE agent_readonly WITH LOGIN PASSWORD 'agent_readonly_password';
GRANT CONNECT ON DATABASE ai_scout TO agent_readonly;
GRANT USAGE ON SCHEMA public TO agent_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_readonly;
