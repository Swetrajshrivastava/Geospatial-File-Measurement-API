from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.jobs import DATABASE_PATH

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine("sqlite:///" + str(DATABASE_PATH.resolve()), poolclass=NullPool)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
