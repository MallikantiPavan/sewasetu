import os
import psycopg2
from contextlib import contextmanager

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "sewasetu"),
        user=os.getenv("DB_USER", "sewasetu"),
        password=os.getenv("DB_PASSWORD", "sewasetu123")
    )

@contextmanager
def get_cursor(commit=False):
    connection=get_connection()

    try:
        cursor=connection.cursor()
        yield cursor

        if commit:
            connection.commit()
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        cursor.close()
        connection.close()

def get_applications_by_mobile(mobile):
    with get_cursor() as cursor:
        cursor.execute(
            "select * from applications where mobile = %s",
            (mobile,),
        )
        return cursor.fetchall()