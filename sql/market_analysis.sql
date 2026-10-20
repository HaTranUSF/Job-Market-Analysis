-- Connect to the database configured by DB_* in .env after an ETL --load.

-- Always inspect coverage before interpreting changes in hiring volume.
SELECT * FROM vw_market_board_coverage ORDER BY started_at DESC, source;

-- Current observed postings, with the observation date available for freshness.
SELECT source, role, COUNT(*) AS postings, MAX(collected_at) AS latest_observation
FROM vw_market_current_jobs
GROUP BY source, role
ORDER BY source, postings DESC;

-- A job contributes at most one match per skill; skill counts can exceed jobs.
SELECT p.role, s.skill, COUNT(*) AS jobs_mentioning_skill
FROM vw_market_current_jobs p
JOIN vw_market_current_skills s ON p.run_id = s.run_id AND p.id = s.job_id
GROUP BY p.role, s.skill
ORDER BY jobs_mentioning_skill DESC
LIMIT 30;

-- Explicit USD pay only; annualized amounts use the assumptions in README.md.
SELECT role, COUNT(salary_min_annual_usd) AS jobs_with_comparable_pay,
       AVG(salary_min_annual_usd) AS average_annual_min_usd,
       AVG(salary_max_annual_usd) AS average_annual_max_usd
FROM vw_market_current_jobs
WHERE salary_currency = 'USD' AND salary_min_annual_usd IS NOT NULL
GROUP BY role
ORDER BY jobs_with_comparable_pay DESC;

-- First seen is our collection date, not the employer's publication date.
SELECT * FROM vw_market_job_history ORDER BY first_seen_at DESC LIMIT 30;

-- Include each supported state for multi-location jobs, counting a job once
-- within a state. Summing state totals can exceed the overall distinct job count.
SELECT state, COUNT(DISTINCT job_id) AS jobs_supporting_state
FROM vw_market_current_locations
GROUP BY state
ORDER BY jobs_supporting_state DESC;
