"""add categories tree + lots.category_id, seed and backfill

Вводит дерево категорий (Аренда/Автовыдача/Прочее → Steam/X → игры) и привязку
лотов к категориям-листам. Сидирует базовое дерево и развешивает существующие
лоты: rental-лоты по играм под Steam, лоты автовыдачи — под «Автовыдача».

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-21

"""
import sqlalchemy as sa
from alembic import op


revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fulfillment', sa.String(length=32), nullable=True),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['categories.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_categories_parent_id', 'categories', ['parent_id'])

    op.add_column('lots', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_index('ix_lots_category_id', 'lots', ['category_id'])
    op.create_foreign_key(
        'fk_lots_category_id', 'lots', 'categories', ['category_id'], ['id'],
    )

    _seed_and_backfill()


def _seed_and_backfill() -> None:
    """Создать базовое дерево и развесить существующие лоты по категориям."""
    bind = op.get_bind()

    def insert_cat(
        title: str,
        parent_id: int | None,
        *,
        fulfillment: str | None = None,
        provider: str | None = None,
        sort: int = 0,
    ) -> int:
        return bind.execute(
            sa.text(
                'INSERT INTO categories '
                '(parent_id, title, sort, fulfillment, provider, active, '
                'created_at, updated_at) '
                'VALUES (:parent_id, :title, :sort, :fulfillment, :provider, true, '
                'now(), now()) RETURNING id',
            ),
            {
                'parent_id': parent_id,
                'title': title,
                'sort': sort,
                'fulfillment': fulfillment,
                'provider': provider,
            },
        ).scalar_one()

    rental_id = insert_cat('Аренда', None, fulfillment='rental', sort=0)
    steam_id = insert_cat('Steam', rental_id, provider='steam', sort=0)
    insert_cat('X', rental_id, provider='x', sort=1)
    auto_id = insert_cat('Автовыдача', None, fulfillment='autodelivery', sort=1)
    insert_cat('Прочее', None, fulfillment='other', sort=2)

    # rental-лоты с указанной игрой → подкатегория-игра под Steam.
    games = bind.execute(
        sa.text(
            "SELECT DISTINCT game FROM lots "
            "WHERE is_autodelivery = false AND game IS NOT NULL AND game <> ''",
        ),
    ).scalars().all()
    for i, game in enumerate(games):
        game_id = insert_cat(game, steam_id, sort=i)
        bind.execute(
            sa.text(
                'UPDATE lots SET category_id = :gid '
                'WHERE is_autodelivery = false AND game = :game',
            ),
            {'gid': game_id, 'game': game},
        )

    # rental-лоты без игры (в т.ч. лоты-продления) → прямо в Steam.
    bind.execute(
        sa.text(
            'UPDATE lots SET category_id = :sid '
            'WHERE is_autodelivery = false AND category_id IS NULL',
        ),
        {'sid': steam_id},
    )
    # лоты автовыдачи → «Автовыдача».
    bind.execute(
        sa.text('UPDATE lots SET category_id = :aid WHERE is_autodelivery = true'),
        {'aid': auto_id},
    )


def downgrade() -> None:
    op.drop_constraint('fk_lots_category_id', 'lots', type_='foreignkey')
    op.drop_index('ix_lots_category_id', table_name='lots')
    op.drop_column('lots', 'category_id')
    op.drop_index('ix_categories_parent_id', table_name='categories')
    op.drop_table('categories')
