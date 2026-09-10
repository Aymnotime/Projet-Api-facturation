"""Test configuration and fixtures."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Organization, User, UserRole


# Create in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create a new session
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    # Rollback all changes after the test
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def test_organization(db_session):
    """Create a test organization for each test."""
    org = Organization(name="Test Organization")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture(scope="function")
def test_user(db_session, test_organization):
    """Create a test user for each test."""
    from app.security import get_password_hash
    
    user = User(
        email="test@example.com",
        password_hash=get_password_hash("testpassword123"),
        full_name="Test User",
        role=UserRole.ADMIN,
        organization_id=test_organization.id,
        is_active=True,
        email_verified=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database dependency override."""
    from fastapi.testclient import TestClient
    
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    
    yield client
    
    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auth_headers(test_organization, db_session):
    """Create authentication headers for API requests."""
    from app.security import generate_api_key
    
    # Create an API key for the test organization
    raw_key, prefix, key_hash = generate_api_key()
    
    api_key = Organization(id=test_organization.id)
    db_session.add(api_key)
    
    from app.models import ApiKey
    api_key_obj = ApiKey(
        organization_id=test_organization.id,
        name="Test API Key",
        prefix=prefix,
        key_hash=key_hash
    )
    db_session.add(api_key_obj)
    db_session.commit()
    
    def get_headers(org=None):
        return {
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json"
        }
    
    return get_headers
