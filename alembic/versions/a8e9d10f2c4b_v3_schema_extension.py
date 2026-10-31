"""v3_schema_extension

Revision ID: a8e9d10f2c4b
Revises: 7fd6911d1d5f
Create Date: 2026-10-31 11:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8e9d10f2c4b'
down_revision: Union[str, Sequence[str], None] = '7fd6911d1d5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. workflows
    op.create_table(
        'workflows',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('definition_json', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    # 2. workflow_runs
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('workflow_id', sa.String(length=64), sa.ForeignKey('workflows.id'), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='RUNNING'),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
        sa.Column('total_tokens', sa.Integer(), server_default='0'),
        sa.Column('total_cost_usd', sa.Float(), server_default='0.0'),
        sa.Column('final_output', sa.Text(), nullable=True),
        sa.Column('workflow_state', sa.JSON(), nullable=True),
        sa.Column('checks', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_workflow_runs_workflow_id', 'workflow_runs', ['workflow_id'])
    op.create_index('ix_workflow_runs_status', 'workflow_runs', ['status'])

    # 3. workflow_step_runs
    op.create_table(
        'workflow_step_runs',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('workflow_run_id', sa.String(length=64), sa.ForeignKey('workflow_runs.id'), nullable=False),
        sa.Column('step_id', sa.String(length=64), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='RUNNING'),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('output_text', sa.Text(), nullable=True),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
        sa.Column('tokens_used', sa.Integer(), server_default='0'),
        sa.Column('estimated_cost_usd', sa.Float(), server_default='0.0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('checks', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_workflow_step_runs_run_id', 'workflow_step_runs', ['workflow_run_id'])

    # 4. worker_nodes
    op.create_table(
        'worker_nodes',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('hostname', sa.String(length=128), nullable=False),
        sa.Column('ip_address', sa.String(length=64), server_default='127.0.0.1'),
        sa.Column('status', sa.String(length=32), server_default='ONLINE'),
        sa.Column('active_jobs_count', sa.Integer(), server_default='0'),
        sa.Column('max_concurrency', sa.Integer(), server_default='4'),
        sa.Column('capabilities', sa.JSON(), nullable=True),
        sa.Column('total_completed_jobs', sa.Integer(), server_default='0'),
        sa.Column('total_failed_jobs', sa.Integer(), server_default='0'),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_worker_nodes_status', 'worker_nodes', ['status'])
    op.create_index('ix_worker_nodes_heartbeat', 'worker_nodes', ['heartbeat_at'])

    # 5. evaluation_datasets
    op.create_table(
        'evaluation_datasets',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(length=32), server_default='1.0.0'),
        sa.Column('item_count', sa.Integer(), server_default='0'),
        sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    # 6. evaluation_dataset_items
    op.create_table(
        'evaluation_dataset_items',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('dataset_id', sa.String(length=64), sa.ForeignKey('evaluation_datasets.id'), nullable=False),
        sa.Column('item_index', sa.Integer(), server_default='0'),
        sa.Column('scenario_id', sa.String(length=64), nullable=True),
        sa.Column('input_data', sa.JSON(), nullable=False),
        sa.Column('expected_output', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_dataset_items_dataset_id', 'evaluation_dataset_items', ['dataset_id'])

    # 7. quality_gates
    op.create_table(
        'quality_gates',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('rules', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    # 8. quality_gate_evaluations
    op.create_table(
        'quality_gate_evaluations',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('gate_id', sa.String(length=64), sa.ForeignKey('quality_gates.id'), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='PASSED'),
        sa.Column('score', sa.Integer(), server_default='100'),
        sa.Column('rule_evaluations', sa.JSON(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_quality_gate_evals_gate_id', 'quality_gate_evaluations', ['gate_id'])
    op.create_index('ix_quality_gate_evals_target_id', 'quality_gate_evaluations', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_quality_gate_evals_target_id', table_name='quality_gate_evaluations')
    op.drop_index('ix_quality_gate_evals_gate_id', table_name='quality_gate_evaluations')
    op.drop_table('quality_gate_evaluations')

    op.drop_table('quality_gates')

    op.drop_index('ix_dataset_items_dataset_id', table_name='evaluation_dataset_items')
    op.drop_table('evaluation_dataset_items')

    op.drop_table('evaluation_datasets')

    op.drop_index('ix_worker_nodes_heartbeat', table_name='worker_nodes')
    op.drop_index('ix_worker_nodes_status', table_name='worker_nodes')
    op.drop_table('worker_nodes')

    op.drop_index('ix_workflow_step_runs_run_id', table_name='workflow_step_runs')
    op.drop_table('workflow_step_runs')

    op.drop_index('ix_workflow_runs_status', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_workflow_id', table_name='workflow_runs')
    op.drop_table('workflow_runs')

    op.drop_table('workflows')
