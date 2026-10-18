
import os

from dotenv import load_dotenv
from sqlalchemy import inspect
from sqlmodel import SQLModel, Session, create_engine

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./social_pulse.db",
)

connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)


def init_db():
    SQLModel.metadata.create_all(engine)
    # Additive migrations keep existing SQLite installs usable when models gain fields.
    additions = {
        "social_records": {
            "monitoring_scope": "VARCHAR NOT NULL DEFAULT 'brand'",
            "query_provenance": "VARCHAR",
            "normalized_text": "VARCHAR",
            "content_hash": "VARCHAR",
            "language_code": "VARCHAR NOT NULL DEFAULT 'und'",
            "language_method": "VARCHAR NOT NULL DEFAULT 'uncertain_heuristic'",
            "is_simulated": "BOOLEAN NOT NULL DEFAULT 0",
            "is_spam": "BOOLEAN NOT NULL DEFAULT 0",
            "provenance_note": "VARCHAR",
            "duplicate_of_record_id": "INTEGER",
            "duplicate_match_score": "FLOAT",
            "duplicate_match_type": "VARCHAR",
            "duplicate_review_state": "VARCHAR NOT NULL DEFAULT 'unreviewed'",
        },
        "record_analyses": {
            "audience_segment": "VARCHAR NOT NULL DEFAULT 'unclear'",
            "audience_need": "VARCHAR NOT NULL DEFAULT 'unclear'",
            "audience_confidence": "FLOAT NOT NULL DEFAULT 0.35",
        },
        "reply_drafts": {
            "reviewed_at": "DATETIME",
        },
        "engagement_opportunities": {
            "action_type": "VARCHAR NOT NULL DEFAULT 'monitor'",
            "pr_objective": "VARCHAR NOT NULL DEFAULT 'audience_education'",
            "stakeholder_type": "VARCHAR",
            "stakeholder_name": "VARCHAR",
            "stakeholder_geography": "VARCHAR",
            "stakeholder_fit_notes": "VARCHAR",
            "stakeholder_review": "VARCHAR NOT NULL DEFAULT 'not_assessed'",
            "partnership_signal": "BOOLEAN NOT NULL DEFAULT 0",
            "manually_added_to_radar": "BOOLEAN NOT NULL DEFAULT 0",
            "confidence": "FLOAT NOT NULL DEFAULT 0.45",
            "review_state": "VARCHAR NOT NULL DEFAULT 'review_required'",
        },
        "content_recommendations": {
            "generated_content_options": "TEXT",
            "collaboration_partner": "VARCHAR",
            "saves": "INTEGER",
            "relevant_stakeholder_engagements": "INTEGER",
            "partnership_enquiries": "INTEGER",
            "media_enquiries": "INTEGER",
            "pr_objective": "VARCHAR NOT NULL DEFAULT 'audience_education'",
            "target_audience": "VARCHAR NOT NULL DEFAULT 'learners and job seekers'",
            "recommended_format": "VARCHAR NOT NULL DEFAULT 'FAQ or carousel'",
            "hook": "VARCHAR NOT NULL DEFAULT ''",
            "distribution_channel": "VARCHAR",
            "priority_score": "INTEGER NOT NULL DEFAULT 50",
            "confidence": "FLOAT NOT NULL DEFAULT 0.4",
            "review_state": "VARCHAR NOT NULL DEFAULT 'review_required'",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(engine)
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def get_session():
    with Session(engine) as session:
        yield session
