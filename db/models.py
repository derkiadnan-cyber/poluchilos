from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class SqliteSession:
    def __init__(self):
        self._engine = create_engine("sqlite:///db.db")
        self._session = sessionmaker(bind=self._engine)
        # self._session = Session()
    
    def __call__(self):
        return self._session()

    def __getattr__(self, name):
        return getattr(self._session, name)
    
    async def create_all(self):
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await self._engine.dispose()

dbSession = SqliteSession()


from sqlalchemy import exc
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Text, BigInteger 
from sqlalchemy.sql import select, insert, update as sqlalchemy_update
from sqlalchemy.sql.functions import func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.strategy_options import load_only


class ModelAdmin:
    @classmethod
    def create(cls, **kwargs) -> int:
        """
        # Создаем новый объект
        :param kwargs: Поля и значения для объекта
        :return: Идентификатор PK
        """

        with dbSession() as session:
            res = session.execute(insert(cls).values(**kwargs))
            session.commit()
            return res.lastrowid

    @classmethod
    def add(cls, **kwargs) -> None:
        """
        # Добавляем новый объект
        :param kwargs: Поля и значения для объекта
        """

        with dbSession() as session:
            session.add(cls(**kwargs))
            session.commit()

    def update(self, **kwargs) -> None:
        """
        # Обновляем текущий объект
        :param kwargs: поля и значения, которые надо поменять
        """

        with dbSession() as session:
            session.execute(
                sqlalchemy_update(self.__class__), [{"id": self.id, **kwargs}]
            )
            session.commit()

    def delete(self) -> None:
        """
        # Удаляем объект
        """
        with dbSession() as session:
            session.delete(self)
            session.commit()

    @classmethod
    def get(cls, **kwargs):
        """
        # Возвращаем одну запись, которая удовлетворяет введенным параметрам
        :param kwargs: поля и значения
        :return: Объект или None
        """

        params = [getattr(cls, key) == val for key, val in kwargs.items()]
        query = select(cls).where(*params)
        try:
            with dbSession() as session:
                results = session.execute(query)
                (result,) = results.one()
                result: cls
                return result
        except exc.NoResultFound:
            return None

    @classmethod
    def filter(cls, **kwargs):
        """
        # Возвращаем все записи, которые удовлетворяют фильтру
        :param kwargs: поля и значения
        :return: ScalarResult, если нашли записи и пустой tuple, если нет
        """

        params = [getattr(cls, key) == val for key, val in kwargs.items()]
        query = select(cls).where(*params)
        try:
            with dbSession() as session:
                results = session.execute(query)
                return results.scalars().all()
        except exc.NoResultFound:
            return ()

    @classmethod
    def all(cls, values=None):
        """
        # Получаем все записи
        :param values: Список полей, которые надо вернуть, если нет, то все (default None)
        :return: Список Class(object)
        """

        if values and isinstance(values, list):
            # Определенные поля
            values = [getattr(cls, val) for val in values if isinstance(val, str)]
            query = select(cls).options(load_only(*values))
        else:
            # Все поля
            query = select(cls)

        with dbSession() as session:
            result = session.execute(query)
            return result.scalars().all()


class User(Base, ModelAdmin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger())
    fullname: Mapped[str] = mapped_column(Text())
    username: Mapped[str] = mapped_column(Text())
    inviter_id: Mapped[int] = mapped_column(BigInteger())
    reg_datetime: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=True
    )

    @classmethod
    def get_or_create(cls, tg_id: int, fullname: str = None,
                      username: str = None, inviter_id: int = None) -> "User":
        user: User = User.get(tg_id=tg_id)
        if user is None:
            user: User = User.get(id=User.create(tg_id=tg_id, fullname=fullname,
                                                 username=username, inviter_id=inviter_id))
        return user


class Payments(Base, ModelAdmin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user: Mapped[int] = mapped_column(ForeignKey("users.id"))
    yoo_id: Mapped[str] = mapped_column(Text())
    link: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(Text())
    reg_datetime: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=True
    )


# engine = create_engine("sqlite:///db.db")
# Base.metadata.create_all(engine)