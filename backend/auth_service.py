"""
Authentication and authorization service
Implements password hashing and user management
"""
import bcrypt
import psycopg2
from database import User, UserRole, row_to_user, get_db_manager


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
        db_manager = get_db_manager()

        try:
            with db_manager.get_cursor() as cursor:
                # Check if user already exists
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    raise ValueError(f"User with email {email} already exists")

                # Create new user
                cursor.execute("""
                    INSERT INTO users (email, password_hash, role)
                    VALUES (%s, %s, %s)
                    RETURNING id, email, password_hash, role, created_at, updated_at
                """, (email, AuthService.hash_password(password), role.value))

                row = cursor.fetchone()
                return row_to_user(row)
        except psycopg2.IntegrityError:
            raise ValueError(f"User with email {email} already exists")

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
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, email, password_hash, role, created_at, updated_at
                FROM users
                WHERE email = %s
            """, (email,))

            row = cursor.fetchone()
            if row:
                user = row_to_user(row)
                if AuthService.verify_password(password, user.password_hash):
                    return user

            return None

    @staticmethod
    def get_user_by_id(user_id: int):
        """Get user by ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, email, password_hash, role, created_at, updated_at
                FROM users
                WHERE id = %s
            """, (user_id,))

            row = cursor.fetchone()
            return row_to_user(row)

    @staticmethod
    def get_user_by_email(email: str):
        """Get user by email"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, email, password_hash, role, created_at, updated_at
                FROM users
                WHERE email = %s
            """, (email,))

            row = cursor.fetchone()
            return row_to_user(row)

    @staticmethod
    def is_admin(user_id: int) -> bool:
        """Check if user is an admin"""
        user = AuthService.get_user_by_id(user_id)
        return user and user.role == UserRole.ADMIN
