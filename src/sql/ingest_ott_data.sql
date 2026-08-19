-- Unity Catalog objects for the OTT recommendation service.
CREATE CATALOG IF NOT EXISTS analytics_dev
COMMENT 'Development analytics catalog';

CREATE SCHEMA IF NOT EXISTS analytics_dev.ott_recommendation
COMMENT 'OTT recommendation service data';

CREATE VOLUME IF NOT EXISTS analytics_dev.ott_recommendation.source_datasets
COMMENT 'Source CSV files for the OTT recommendation service';

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.movies
USING DELTA
COMMENT 'OTT movie catalog'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/movies.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'movie_id STRING, title STRING, release_date DATE, primary_genre STRING, genre_detail STRING, production_country STRING, original_language STRING, runtime_minutes INT, content_rating STRING, director_name STRING, studio_name STRING, production_budget_krw BIGINT, theatrical_admissions BIGINT, platform_release_date DATE, is_platform_original BOOLEAN, setting STRING, protagonist STRING, core_conflict STRING, keywords STRING, logline STRING'
);

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.critics
USING DELTA
COMMENT 'Movie critic profiles'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/critics.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'critic_id STRING, critic_name STRING, pen_name STRING, publication_name STRING, region STRING, years_experience INT, specialty_genre STRING, education_background STRING, criticism_style STRING, primary_medium STRING, email STRING, joined_date DATE, is_top_critic BOOLEAN, profile_note STRING'
);

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.critic_reviews
USING DELTA
COMMENT 'Professional critic reviews for OTT movies'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/critic_reviews.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'critic_review_id STRING, critic_id STRING, movie_id STRING, score_100 INT, letter_grade STRING, review_title STRING, review_text STRING, reviewed_at TIMESTAMP, verdict STRING, recommended BOOLEAN'
);

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.user_reviews
USING DELTA
COMMENT 'OTT user ratings and written reviews'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/user_reviews.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'review_id STRING, user_id STRING, movie_id STRING, source_viewing_id STRING, rating DOUBLE, review_title STRING, review_text STRING, reviewed_at TIMESTAMP'
);

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.users
USING DELTA
COMMENT 'OTT subscriber profiles for recommendation experiments'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/users.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'user_id STRING, display_name STRING, birth_year INT, gender STRING, region STRING, preferred_language STRING, signup_date DATE, subscription_plan STRING, preferred_genre STRING, preferred_device STRING, watch_time_preference STRING, household_type STRING, account_status STRING'
);

CREATE OR REPLACE TABLE analytics_dev.ott_recommendation.viewing_history
USING DELTA
COMMENT 'OTT viewing sessions and completion behavior'
AS
SELECT *
FROM read_files(
  '/Volumes/analytics_dev/ott_recommendation/source_datasets/viewing_history.csv',
  format => 'csv',
  header => true,
  encoding => 'UTF-8',
  mode => 'FAILFAST',
  schema => 'viewing_id STRING, user_id STRING, movie_id STRING, started_at TIMESTAMP, ended_at TIMESTAMP, watch_minutes INT, completion_pct DOUBLE, playback_status STRING, device_type STRING, streaming_quality STRING, viewing_country STRING, rewatch_number INT, discovery_source STRING'
);

SELECT 'movies' AS table_name, COUNT(*) AS row_count
FROM analytics_dev.ott_recommendation.movies
UNION ALL
SELECT 'critics', COUNT(*)
FROM analytics_dev.ott_recommendation.critics
UNION ALL
SELECT 'critic_reviews', COUNT(*)
FROM analytics_dev.ott_recommendation.critic_reviews
UNION ALL
SELECT 'user_reviews', COUNT(*)
FROM analytics_dev.ott_recommendation.user_reviews
UNION ALL
SELECT 'users', COUNT(*)
FROM analytics_dev.ott_recommendation.users
UNION ALL
SELECT 'viewing_history', COUNT(*)
FROM analytics_dev.ott_recommendation.viewing_history
ORDER BY table_name;
