"""
Authentication and authorization service
Implements password hashing and user management
"""
import bcrypt
from database import User, UserRole, get_session
from sqlalchemy.exc import IntegrityError


class AuthService:
    """Service for user authentication and authorization"""

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt

        Args:
            password: Plain text password

        Returns:
            Hashed password
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash

        Args:
            password: Plain text password
            password_hash: Hashed password

        Returns:
            True if password matches, False otherwise
        """
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

    @staticmethod
    def create_user(email: str, password: str, role: UserRole = UserRole.CUSTOMER):
        """
        Create a new user

        Args:
            email: User email
            password: Plain text password
            role: User role

        Returns:
            Created user object

        Raises:
            ValueError: If user already exists
        """
        session = get_session()
        try:
            # Check if user already exists
            existing_user = session.query(User).filter_by(email=email).first()
            if existing_user:
                raise ValueError(f"User with email {email} already exists")

            # Create new user
            user = User(
                email=email,
                password_hash=AuthService.hash_password(password),
                role=role
            )
            session.add(user)
            session.commit()
            session.refresh(user)

            # Expunge to make object usable after session closes
            session.expunge(user)

            return user
        except IntegrityError:
            session.rollback()
            raise ValueError(f"User with email {email} already exists")
        finally:
            session.close()

    @staticmethod
    def authenticate(email: str, password: str):
        """
        Authenticate a user

        Args:
            email: User email
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        session = get_session()
        try:
            user = session.query(User).filter_by(email=email).first()
            if user and AuthService.verify_password(password, user.password_hash):
                session.expunge(user)
                return user
            return None
        finally:
            session.close()

    @staticmethod
    def get_user_by_id(user_id: int):
        """Get user by ID"""
        session = get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()

            if user:
                session.expunge(user)

            return user
        finally:
            session.close()

    @staticmethod
    def get_user_by_email(email: str):
        """Get user by email"""
        session = get_session()
        try:
            user = session.query(User).filter_by(email=email).first()

            if user:
                session.expunge(user)

            return user
        finally:
            session.close()

    @staticmethod
    def is_admin(user_id: int) -> bool:
        """Check if user is an admin"""
        user = AuthService.get_user_by_id(user_id)
        return user and user.role == UserRole.ADMIN
