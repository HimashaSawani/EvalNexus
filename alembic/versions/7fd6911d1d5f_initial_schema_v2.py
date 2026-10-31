"""initial_schema_v2

Revision ID: 7fd6911d1d5f
Revises: 
Create Date: 2026-10-31 09:47:28.324182

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fd6911d1d5f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. agent_versions
    op.create_table(
        'agent_versions',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('model_name', sa.String(length=64), nullable=False, server_default='gemini-1.5-flash'),
        sa.Column('temperature', sa.Integer(), server_default='0'),
        sa.Column('tool_schema_version', sa.String(length=32), server_default='v1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 2. scenario_versions
    op.create_table(
        'scenario_versions',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('fixed_clock', sa.DateTime(), nullable=False),
        sa.Column('initial_data', sa.JSON(), nullable=False),
        sa.Column('customer_messages', sa.JSON(), nullable=False),
        sa.Column('fault_configs', sa.JSON(), nullable=True),
        sa.Column('expected_checks', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 3. runs
    op.create_table(
        'runs',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('agent_version_id', sa.String(length=64), sa.ForeignKey('agent_versions.id'), nullable=False),
        sa.Column('provider_type', sa.String(length=32), server_default='mock'),
        sa.Column('model_name', sa.String(length=64), server_default='mock-deterministic-v1'),
        sa.Column('is_mock', sa.Integer(), server_default='1'),
        sa.Column('execution_config', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='QUEUED'),
        sa.Column('total_scenarios', sa.Integer(), server_default='0'),
        sa.Column('passed_scenarios', sa.Integer(), server_default='0'),
        sa.Column('failed_scenarios', sa.Integer(), server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 4. scenario_runs
    op.create_table(
        'scenario_runs',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('run_id', sa.String(length=64), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('scenario_version_id', sa.String(length=64), sa.ForeignKey('scenario_versions.id'), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='RUNNING'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
    )

    # 5. trace_events
    op.create_table(
        'trace_events',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('scenario_run_id', sa.String(length=64), sa.ForeignKey('scenario_runs.id'), nullable=False),
        sa.Column('seq_num', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('tool_name', sa.String(length=64), nullable=True),
        sa.Column('tool_arguments', sa.JSON(), nullable=True),
        sa.Column('tool_result', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('cost_estimate', sa.Integer(), server_default='0'),
    )
    op.create_index('ix_trace_run_seq', 'trace_events', ['scenario_run_id', 'seq_num'])

    # 6. check_results
    op.create_table(
        'check_results',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('scenario_run_id', sa.String(length=64), sa.ForeignKey('scenario_runs.id'), nullable=False),
        sa.Column('check_name', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
    )

    # 7. customers
    op.create_table(
        'customers',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('scenario_run_id', sa.String(length=64), sa.ForeignKey('scenario_runs.id'), primary_key=True, index=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('email', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 8. orders
    op.create_table(
        'orders',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('scenario_run_id', sa.String(length=64), sa.ForeignKey('scenario_runs.id'), primary_key=True, index=True),
        sa.Column('customer_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('total_amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=8), server_default='USD'),
        sa.Column('delivery_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 9. refund_requests
    op.create_table(
        'refund_requests',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('scenario_run_id', sa.String(length=64), sa.ForeignKey('scenario_runs.id'), primary_key=True, index=True),
        sa.Column('order_id', sa.String(length=64), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=8), server_default='USD'),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('operation_key', sa.String(length=128), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('idempotency_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_refund_op_key', 'refund_requests', ['scenario_run_id', 'order_id', 'operation_key'])

    # 10. queue_jobs
    op.create_table(
        'queue_jobs',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('run_id', sa.String(length=64), sa.ForeignKey('runs.id'), nullable=False, index=True),
        sa.Column('status', sa.String(length=32), server_default='QUEUED', index=True),
        sa.Column('agent_version_id', sa.String(length=64), sa.ForeignKey('agent_versions.id'), nullable=False),
        sa.Column('provider_type', sa.String(length=32), server_default='mock'),
        sa.Column('model_name', sa.String(length=64), nullable=False),
        sa.Column('scenario_ids', sa.JSON(), nullable=False),
        sa.Column('execution_config', sa.JSON(), nullable=True),
        sa.Column('is_paid', sa.Integer(), server_default='0'),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('worker_id', sa.String(length=64), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    # 11. custom_agents
    op.create_table(
        'custom_agents',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('endpoint_url', sa.String(length=512), nullable=False),
        sa.Column('auth_header_name', sa.String(length=64), server_default='Authorization'),
        sa.Column('auth_token_masked', sa.String(length=64), nullable=True),
        sa.Column('auth_token_secret', sa.Text(), nullable=True),
        sa.Column('timeout_sec', sa.Integer(), server_default='15'),
        sa.Column('is_active', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    # 12. custom_scenarios
    op.create_table(
        'custom_scenarios',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=64), server_default='CUSTOM'),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('scenario_data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('custom_scenarios')
    op.drop_table('custom_agents')
    op.drop_table('queue_jobs')
    op.drop_index('ix_refund_op_key', table_name='refund_requests')
    op.drop_table('refund_requests')
    op.drop_table('orders')
    op.drop_table('customers')
    op.drop_table('check_results')
    op.drop_index('ix_trace_run_seq', table_name='trace_events')
    op.drop_table('trace_events')
    op.drop_table('scenario_runs')
    op.drop_table('runs')
    op.drop_table('scenario_versions')
    op.drop_table('agent_versions')
