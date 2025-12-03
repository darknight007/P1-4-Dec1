# core/infrastructure.py
import os
import boto3
from typing import Any

# "AWS" or "LOCAL"
MODE = os.environ.get("SCROOGE_ENV", "AWS")

class InfrastructureProvider:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(InfrastructureProvider, cls).__new__(cls)
            cls._instance._init_resources()
        return cls._instance

    def _init_resources(self):
        self.mode = MODE
        if self.mode == "LOCAL":
            from core.local_adapter import LocalDataManager, MockS3, MockSQS
            self._db_manager = LocalDataManager()
            self.s3 = MockS3()
            self.sqs = MockSQS()
            # DynamoDB resource wrapper
            self.dynamodb = self._LocalDynamoResource(self._db_manager)
        else:
            # AWS Mode
            region = os.environ.get("AWS_REGION", "ap-south-1")
            self.dynamodb = boto3.resource('dynamodb', region_name=region)
            self.s3 = boto3.client('s3', region_name=region)
            self.sqs = boto3.client('sqs', region_name=region)

    def get_table(self, table_name: str):
        """Returns a Table object (boto3 or mock)."""
        return self.dynamodb.Table(table_name)

    def get_s3_client(self):
        return self.s3

    def get_sqs_client(self):
        return self.sqs

    class _LocalDynamoResource:
        def __init__(self, manager):
            self.manager = manager
        def Table(self, name):
            return self.manager.get_table(name)

# Singleton Accessor
infra = InfrastructureProvider()
