from sqlalchemy.ext.declarative import declarative_base

# Create the Declarative Base
# This class will be inherited by all ORM models (e.g. Recording, Device)
Base = declarative_base()
