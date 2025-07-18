import copy
import re
import uuid
from datetime import datetime
from decimal import Decimal

import boto3
import pytest
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import Binary
from botocore.exceptions import ClientError

import moto.dynamodb.comparisons
import moto.dynamodb.models
from moto import mock_aws, settings
from moto.core import DEFAULT_ACCOUNT_ID as ACCOUNT_ID
from moto.dynamodb import dynamodb_backends

from . import dynamodb_aws_verified


@mock_aws
@pytest.mark.parametrize(
    "names",
    [[], ["TestTable"], ["TestTable1", "TestTable2"]],
    ids=["no-table", "one-table", "multiple-tables"],
)
def test_list_tables_boto3(names):
    conn = boto3.client("dynamodb", region_name="us-west-2")
    for name in names:
        conn.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
    assert conn.list_tables()["TableNames"] == names


@mock_aws
def test_list_tables_paginated():
    conn = boto3.client("dynamodb", region_name="us-west-2")
    for name in ["name1", "name2", "name3"]:
        conn.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    res = conn.list_tables(Limit=2)
    assert res["TableNames"] == ["name1", "name2"]
    assert res["LastEvaluatedTableName"] == "name2"

    res = conn.list_tables(Limit=1, ExclusiveStartTableName="name1")
    assert res["TableNames"] == ["name2"]
    assert res["LastEvaluatedTableName"] == "name2"

    res = conn.list_tables(ExclusiveStartTableName="name1")
    assert res["TableNames"] == ["name2", "name3"]
    assert "LastEvaluatedTableName" not in res


@mock_aws
def test_describe_missing_table_boto3():
    conn = boto3.client("dynamodb", region_name="us-west-2")
    with pytest.raises(ClientError) as ex:
        conn.describe_table(TableName="messages")
    assert ex.value.response["Error"]["Code"] == "ResourceNotFoundException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "Requested resource not found: Table: messages not found"
    )


@mock_aws
def test_describe_table_using_arn():
    name = "TestTable"
    conn = boto3.client("dynamodb", region_name="us-west-2")
    table_arn = conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )["TableDescription"]["TableArn"]

    conn.describe_table(TableName=table_arn)

    conn.put_item(TableName=table_arn, Item={"id": {"S": "n/a"}})
    conn.get_item(TableName=table_arn, Key={"id": {"S": "n/a"}})
    conn.query(
        TableName=table_arn,
        KeyConditionExpression="id = :val",
        ExpressionAttributeValues={":val": {"S": "n/a"}},
    )
    conn.scan(TableName=table_arn)
    conn.delete_item(TableName=table_arn, Key={"id": {"S": "n/a"}})

    conn.update_table(
        TableName=table_arn,
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
    )
    conn.update_time_to_live(
        TableName=table_arn,
        TimeToLiveSpecification={"Enabled": False, "AttributeName": "a"},
    )
    conn.describe_time_to_live(TableName=table_arn)

    conn.delete_table(TableName=table_arn)

    with pytest.raises(ClientError):
        conn.describe_table(TableName=table_arn)


@mock_aws
def test_list_table_tags():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table_description = conn.describe_table(TableName=name)
    arn = table_description["Table"]["TableArn"]

    # Tag table
    tags = [
        {"Key": "TestTag", "Value": "TestValue"},
        {"Key": "TestTag2", "Value": "TestValue2"},
    ]
    conn.tag_resource(ResourceArn=arn, Tags=tags)

    # Check tags
    resp = conn.list_tags_of_resource(ResourceArn=arn)
    assert resp["Tags"] == tags

    # Remove 1 tag
    conn.untag_resource(ResourceArn=arn, TagKeys=["TestTag"])

    # Check tags
    resp = conn.list_tags_of_resource(ResourceArn=arn)
    assert resp["Tags"] == [{"Key": "TestTag2", "Value": "TestValue2"}]


@mock_aws
def test_list_table_tags_empty():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table_description = conn.describe_table(TableName=name)
    arn = table_description["Table"]["TableArn"]
    resp = conn.list_tags_of_resource(ResourceArn=arn)
    assert resp["Tags"] == []


@mock_aws
def test_list_table_tags_paginated():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table_description = conn.describe_table(TableName=name)
    arn = table_description["Table"]["TableArn"]
    for i in range(11):
        tags = [{"Key": f"TestTag{i}", "Value": "TestValue"}]
        conn.tag_resource(ResourceArn=arn, Tags=tags)
    resp = conn.list_tags_of_resource(ResourceArn=arn)
    assert len(resp["Tags"]) == 10
    assert "NextToken" in resp.keys()
    resp2 = conn.list_tags_of_resource(ResourceArn=arn, NextToken=resp["NextToken"])
    assert len(resp2["Tags"]) == 1
    assert "NextToken" not in resp2.keys()


@mock_aws
def test_list_not_found_table_tags():
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    arn = "DymmyArn"
    try:
        conn.list_tags_of_resource(ResourceArn=arn)
    except ClientError as exception:
        assert exception.response["Error"]["Code"] == "ResourceNotFoundException"


@mock_aws
def test_item_add_empty_string_hash_key_exception():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    with pytest.raises(ClientError) as ex:
        conn.put_item(
            TableName=name,
            Item={
                "forum_name": {"S": ""},
                "subject": {"S": "Check this out!"},
                "Body": {"S": "http://url_to_lolcat.gif"},
                "SentBy": {"S": "someone@somewhere.edu"},
                "ReceivedTime": {"S": "12/9/2011 11:36:03 PM"},
            },
        )

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "One or more parameter values were invalid: An AttributeValue may not contain an empty string. Key: forum_name"
    )


@mock_aws
def test_item_add_empty_string_range_key_exception():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "ReceivedTime", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "ReceivedTime", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    with pytest.raises(ClientError) as ex:
        conn.put_item(
            TableName=name,
            Item={
                "forum_name": {"S": "LOLCat Forum"},
                "subject": {"S": "Check this out!"},
                "Body": {"S": "http://url_to_lolcat.gif"},
                "SentBy": {"S": "someone@somewhere.edu"},
                "ReceivedTime": {"S": ""},
            },
        )

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "One or more parameter values were invalid: An AttributeValue may not contain an empty string. Key: ReceivedTime"
    )


@mock_aws
def test_item_add_empty_string_attr_no_exception():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    conn.put_item(
        TableName=name,
        Item={
            "forum_name": {"S": "LOLCat Forum"},
            "subject": {"S": "Check this out!"},
            "Body": {"S": "http://url_to_lolcat.gif"},
            "SentBy": {"S": ""},
            "ReceivedTime": {"S": "12/9/2011 11:36:03 PM"},
        },
    )


@mock_aws
def test_update_item_with_empty_string_attr_no_exception():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    conn.put_item(
        TableName=name,
        Item={
            "forum_name": {"S": "LOLCat Forum"},
            "subject": {"S": "Check this out!"},
            "Body": {"S": "http://url_to_lolcat.gif"},
            "SentBy": {"S": "test"},
            "ReceivedTime": {"S": "12/9/2011 11:36:03 PM"},
        },
    )

    conn.update_item(
        TableName=name,
        Key={"forum_name": {"S": "LOLCat Forum"}},
        UpdateExpression="set Body=:Body",
        ExpressionAttributeValues={":Body": {"S": ""}},
    )


@mock_aws
def test_query_invalid_table():
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )
    try:
        conn.query(
            TableName="invalid_table",
            KeyConditionExpression="index1 = :partitionkeyval",
            ExpressionAttributeValues={":partitionkeyval": {"S": "test"}},
        )
    except ClientError as exception:
        assert exception.response["Error"]["Code"] == "ResourceNotFoundException"


@mock_aws
def test_put_item_with_special_chars():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )

    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    conn.put_item(
        TableName=name,
        Item={
            "forum_name": {"S": "LOLCat Forum"},
            "subject": {"S": "Check this out!"},
            "Body": {"S": "http://url_to_lolcat.gif"},
            "SentBy": {"S": "test"},
            "ReceivedTime": {"S": "12/9/2011 11:36:03 PM"},
            '"': {"S": "foo"},
        },
    )


@mock_aws
def test_put_item_with_streams():
    name = "TestTable"
    conn = boto3.client(
        "dynamodb",
        region_name="us-west-2",
        aws_access_key_id="ak",
        aws_secret_access_key="sk",
    )

    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": "NEW_AND_OLD_IMAGES",
        },
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    conn.put_item(
        TableName=name,
        Item={
            "forum_name": {"S": "LOLCat Forum"},
            "subject": {"S": "Check this out!"},
            "Body": {"S": "http://url_to_lolcat.gif"},
            "SentBy": {"S": "test"},
            "Data": {"M": {"Key1": {"S": "Value1"}, "Key2": {"S": "Value2"}}},
        },
    )

    result = conn.get_item(TableName=name, Key={"forum_name": {"S": "LOLCat Forum"}})

    assert result["Item"] == {
        "forum_name": {"S": "LOLCat Forum"},
        "subject": {"S": "Check this out!"},
        "Body": {"S": "http://url_to_lolcat.gif"},
        "SentBy": {"S": "test"},
        "Data": {"M": {"Key1": {"S": "Value1"}, "Key2": {"S": "Value2"}}},
    }

    if not settings.TEST_SERVER_MODE:
        table = dynamodb_backends[ACCOUNT_ID]["us-west-2"].get_table(name)
        assert len(table.stream_shard.items) == 1
        stream_record = table.stream_shard.items[0].record
        assert stream_record["eventName"] == "INSERT"
        assert stream_record["dynamodb"]["SizeBytes"] == 447


@mock_aws
def test_basic_projection_expression_using_get_item():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    table = dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={"forum_name": "the-key", "subject": "123", "body": "some test message"}
    )

    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
        }
    )
    result = table.get_item(
        Key={"forum_name": "the-key", "subject": "123"},
        ProjectionExpression="body, subject",
    )

    assert result["Item"] == {"subject": "123", "body": "some test message"}

    # The projection expression should not remove data from storage
    result = table.get_item(Key={"forum_name": "the-key", "subject": "123"})

    assert result["Item"] == {
        "forum_name": "the-key",
        "subject": "123",
        "body": "some test message",
    }

    # Running this against AWS DDB gives an exception so make sure it also fails.:
    with pytest.raises(client.exceptions.ClientError):
        # botocore.exceptions.ClientError: An error occurred (ValidationException) when calling the GetItem
        # operation: "Can not use both expression and non-expression parameters in the same request:
        #  Non-expression parameters: {AttributesToGet} Expression parameters: {ProjectionExpression}"
        table.get_item(
            Key={"forum_name": "the-key", "subject": "123"},
            ProjectionExpression="body",
            AttributesToGet=["body"],
        )


@mock_aws
def test_basic_projection_expressions_using_scan():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={"forum_name": "the-key", "subject": "123", "body": "some test message"}
    )

    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
        }
    )
    # Test a scan returning all items
    results = table.scan(
        FilterExpression=Key("forum_name").eq("the-key"),
        ProjectionExpression="body, subject",
    )

    assert "body" in results["Items"][0]
    assert results["Items"][0]["body"] == "some test message"
    assert "subject" in results["Items"][0]

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "1234",
            "body": "yet another test message",
        }
    )

    results = table.scan(
        FilterExpression=Key("forum_name").eq("the-key"), ProjectionExpression="body"
    )

    bodies = [item["body"] for item in results["Items"]]
    assert "some test message" in bodies
    assert "yet another test message" in bodies
    assert "subject" not in results["Items"][0]
    assert "forum_name" not in results["Items"][0]
    assert "subject" not in results["Items"][1]
    assert "forum_name" not in results["Items"][1]

    # The projection expression should not remove data from storage
    results = table.query(KeyConditionExpression=Key("forum_name").eq("the-key"))
    assert "subject" in results["Items"][0]
    assert "body" in results["Items"][1]
    assert "forum_name" in results["Items"][1]


@mock_aws
def test_nested_projection_expression_using_get_item():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "forum_name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level2": {"id": "id2", "include": "all"},
                "level3": {"id": "irrelevant"},
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "forum_name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a get_item returning all items
    result = table.get_item(
        Key={"forum_name": "key1"},
        ProjectionExpression="nested.level1.id, nested.level2",
    )["Item"]
    assert result == {
        "nested": {"level1": {"id": "id1"}, "level2": {"id": "id2", "include": "all"}}
    }
    # Assert actual data has not been deleted
    result = table.get_item(Key={"forum_name": "key1"})["Item"]
    assert result == {
        "foo": "bar",
        "forum_name": "key1",
        "nested": {
            "level1": {"id": "id1", "att": "irrelevant"},
            "level2": {"id": "id2", "include": "all"},
            "level3": {"id": "irrelevant"},
        },
    }


@mock_aws
def test_basic_projection_expressions_using_query():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={"forum_name": "the-key", "subject": "123", "body": "some test message"}
    )
    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
        }
    )

    # Test a query returning all items
    result = table.query(
        KeyConditionExpression=Key("forum_name").eq("the-key"),
        ProjectionExpression="body, subject",
    )["Items"][0]

    assert "body" in result
    assert result["body"] == "some test message"
    assert "subject" in result
    assert "forum_name" not in result

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "1234",
            "body": "yet another test message",
        }
    )

    items = table.query(
        KeyConditionExpression=Key("forum_name").eq("the-key"),
        ProjectionExpression="body",
    )["Items"]

    assert "body" in items[0]
    assert "subject" not in items[0]
    assert items[0]["body"] == "some test message"
    assert "body" in items[1]
    assert "subject" not in items[1]
    assert items[1]["body"] == "yet another test message"

    # The projection expression should not remove data from storage
    items = table.query(KeyConditionExpression=Key("forum_name").eq("the-key"))["Items"]
    assert "subject" in items[0]
    assert "body" in items[1]
    assert "forum_name" in items[1]


@mock_aws
def test_nested_projection_expression_using_query():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level2": {"id": "id2", "include": "all"},
                "level3": {"id": "irrelevant"},
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a query returning nested attributes
    result = table.query(
        KeyConditionExpression=Key("name").eq("key1"),
        ProjectionExpression="nested.level1.id, nested.level2",
    )
    assert result["ScannedCount"] == 1
    item = result["Items"][0]

    assert "nested" in item
    assert item["nested"] == {
        "level1": {"id": "id1"},
        "level2": {"id": "id2", "include": "all"},
    }
    assert "foo" not in item

    # Assert actual data has not been deleted
    result = table.query(KeyConditionExpression=Key("name").eq("key1"))["Items"][0]
    assert result == {
        "foo": "bar",
        "name": "key1",
        "nested": {
            "level1": {"id": "id1", "att": "irrelevant"},
            "level2": {"id": "id2", "include": "all"},
            "level3": {"id": "irrelevant"},
        },
    }


@mock_aws
def test_nested_projection_expression_using_scan():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "forum_name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level2": {"id": "id2", "include": "all"},
                "level3": {"id": "irrelevant"},
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "forum_name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a scan
    results = table.scan(
        FilterExpression=Key("forum_name").eq("key1"),
        ProjectionExpression="nested.level1.id, nested.level2",
    )["Items"]
    assert results == [
        {
            "nested": {
                "level1": {"id": "id1"},
                "level2": {"include": "all", "id": "id2"},
            }
        }
    ]
    # Assert original data is still there
    results = table.scan(FilterExpression=Key("forum_name").eq("key1"))["Items"]
    assert results == [
        {
            "forum_name": "key1",
            "foo": "bar",
            "nested": {
                "level1": {"att": "irrelevant", "id": "id1"},
                "level2": {"include": "all", "id": "id2"},
                "level3": {"id": "irrelevant"},
            },
        }
    ]


@mock_aws
def test_basic_projection_expression_using_get_item_with_attr_expression_names():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    table = dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "123",
            "body": "some test message",
            "attachment": "something",
        }
    )

    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
            "attachment": "something",
        }
    )
    result = table.get_item(
        Key={"forum_name": "the-key", "subject": "123"},
        ProjectionExpression="#rl, #rt, subject",
        ExpressionAttributeNames={"#rl": "body", "#rt": "attachment"},
    )

    assert result["Item"] == {
        "subject": "123",
        "body": "some test message",
        "attachment": "something",
    }


@mock_aws
def test_basic_projection_expressions_using_query_with_attr_expression_names():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    table = dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "123",
            "body": "some test message",
            "attachment": "something",
        }
    )

    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
            "attachment": "something",
        }
    )
    # Test a query returning all items

    results = table.query(
        KeyConditionExpression=Key("forum_name").eq("the-key"),
        ProjectionExpression="#rl, #rt, subject",
        ExpressionAttributeNames={"#rl": "body", "#rt": "attachment"},
    )

    assert results["Items"][0]["body"] == "some test message"
    assert results["Items"][0]["subject"] == "123"
    assert results["Items"][0]["attachment"] == "something"


@mock_aws
def test_nested_projection_expression_using_get_item_with_attr_expression():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "forum_name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level.2": {"id": "id2", "include": "all"},
                "level3": {
                    "id": "irrelevant",
                    "children": [{"Name": "child_a"}, {"Name": "child_b"}],
                },
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "forum_name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a get_item returning all items
    result = table.get_item(
        Key={"forum_name": "key1"},
        ProjectionExpression="#nst.level1.id, #nst.#lvl2",
        ExpressionAttributeNames={"#nst": "nested", "#lvl2": "level.2"},
    )["Item"]
    assert result == {
        "nested": {"level1": {"id": "id1"}, "level.2": {"id": "id2", "include": "all"}}
    }
    # Assert actual data has not been deleted
    result = table.get_item(Key={"forum_name": "key1"})["Item"]
    assert result == {
        "foo": "bar",
        "forum_name": "key1",
        "nested": {
            "level1": {"id": "id1", "att": "irrelevant"},
            "level.2": {"id": "id2", "include": "all"},
            "level3": {
                "id": "irrelevant",
                "children": [{"Name": "child_a"}, {"Name": "child_b"}],
            },
        },
    }

    # Test a get_item retrieving children
    result = table.get_item(
        Key={"forum_name": "key1"},
        ProjectionExpression="nested.level3.children[0].Name",
    )["Item"]
    assert result == {"nested": {"level3": {"children": [{"Name": "child_a"}]}}}


@mock_aws
def test_nested_projection_expression_using_query_with_attr_expression_names():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level2": {"id": "id2", "include": "all"},
                "level3": {"id": "irrelevant"},
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a query returning all items
    result = table.query(
        KeyConditionExpression=Key("name").eq("key1"),
        ProjectionExpression="#nst.level1.id, #nst.#lvl2",
        ExpressionAttributeNames={"#nst": "nested", "#lvl2": "level2"},
    )["Items"][0]

    assert result["nested"] == {
        "level1": {"id": "id1"},
        "level2": {"id": "id2", "include": "all"},
    }
    assert "foo" not in result
    # Assert actual data has not been deleted
    result = table.query(KeyConditionExpression=Key("name").eq("key1"))["Items"][0]
    assert result == {
        "foo": "bar",
        "name": "key1",
        "nested": {
            "level1": {"id": "id1", "att": "irrelevant"},
            "level2": {"id": "id2", "include": "all"},
            "level3": {"id": "irrelevant"},
        },
    }


@mock_aws
def test_basic_projection_expressions_using_scan_with_attr_expression_names():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    table = dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "123",
            "body": "some test message",
            "attachment": "something",
        }
    )

    table.put_item(
        Item={
            "forum_name": "not-the-key",
            "subject": "123",
            "body": "some other test message",
            "attachment": "something",
        }
    )
    # Test a scan returning all items

    results = table.scan(
        FilterExpression=Key("forum_name").eq("the-key"),
        ProjectionExpression="#rl, #rt, subject",
        ExpressionAttributeNames={"#rl": "body", "#rt": "attachment"},
    )

    assert "body" in results["Items"][0]
    assert "attachment" in results["Items"][0]
    assert "subject" in results["Items"][0]
    assert "form_name" not in results["Items"][0]

    # Test without a FilterExpression
    results = table.scan(
        ProjectionExpression="#rl, #rt, subject",
        ExpressionAttributeNames={"#rl": "body", "#rt": "attachment"},
    )

    assert "body" in results["Items"][0]
    assert "attachment" in results["Items"][0]
    assert "subject" in results["Items"][0]
    assert "form_name" not in results["Items"][0]


@mock_aws
def test_nested_projection_expression_using_scan_with_attr_expression_names():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "forum_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.put_item(
        Item={
            "forum_name": "key1",
            "nested": {
                "level1": {"id": "id1", "att": "irrelevant"},
                "level2": {"id": "id2", "include": "all"},
                "level3": {"id": "irrelevant"},
            },
            "foo": "bar",
        }
    )
    table.put_item(
        Item={
            "forum_name": "key2",
            "nested": {"id": "id2", "incode": "code2"},
            "foo": "bar",
        }
    )

    # Test a scan
    results = table.scan(
        FilterExpression=Key("forum_name").eq("key1"),
        ProjectionExpression="#nst.level1.id, #nst.#lvl2",
        ExpressionAttributeNames={"#nst": "nested", "#lvl2": "level2"},
    )["Items"]
    assert results == [
        {
            "nested": {
                "level1": {"id": "id1"},
                "level2": {"include": "all", "id": "id2"},
            }
        }
    ]
    # Assert original data is still there
    results = table.scan(FilterExpression=Key("forum_name").eq("key1"))["Items"]
    assert results == [
        {
            "forum_name": "key1",
            "foo": "bar",
            "nested": {
                "level1": {"att": "irrelevant", "id": "id1"},
                "level2": {"include": "all", "id": "id2"},
                "level3": {"id": "irrelevant"},
            },
        }
    ]


@mock_aws
def test_put_empty_item():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        AttributeDefinitions=[{"AttributeName": "structure_id", "AttributeType": "S"}],
        TableName="test",
        KeySchema=[{"AttributeName": "structure_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )
    table = dynamodb.Table("test")

    with pytest.raises(ClientError) as ex:
        table.put_item(Item={})
    assert (
        ex.value.response["Error"]["Message"]
        == "One or more parameter values were invalid: Missing the key structure_id in the item"
    )
    assert ex.value.response["Error"]["Code"] == "ValidationException"


@mock_aws
def test_put_item_nonexisting_hash_key():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        AttributeDefinitions=[{"AttributeName": "structure_id", "AttributeType": "S"}],
        TableName="test",
        KeySchema=[{"AttributeName": "structure_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )
    table = dynamodb.Table("test")

    with pytest.raises(ClientError) as ex:
        table.put_item(Item={"a_terribly_misguided_id_attribute": "abcdef"})
    assert (
        ex.value.response["Error"]["Message"]
        == "One or more parameter values were invalid: Missing the key structure_id in the item"
    )
    assert ex.value.response["Error"]["Code"] == "ValidationException"


@mock_aws
def test_put_item_nonexisting_range_key():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        AttributeDefinitions=[
            {"AttributeName": "structure_id", "AttributeType": "S"},
            {"AttributeName": "added_at", "AttributeType": "N"},
        ],
        TableName="test",
        KeySchema=[
            {"AttributeName": "structure_id", "KeyType": "HASH"},
            {"AttributeName": "added_at", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )
    table = dynamodb.Table("test")

    with pytest.raises(ClientError) as ex:
        table.put_item(Item={"structure_id": "abcdef"})
    assert (
        ex.value.response["Error"]["Message"]
        == "One or more parameter values were invalid: Missing the key added_at in the item"
    )
    assert ex.value.response["Error"]["Code"] == "ValidationException"


def test_filter_expression():
    row1 = moto.dynamodb.models.Item(
        hash_key=None,
        range_key=None,
        attrs={
            "Id": {"N": "8"},
            "Subs": {"N": "5"},
            "Des": {"S": "Some description"},
            "KV": {"SS": ["test1", "test2"]},
        },
    )
    row2 = moto.dynamodb.models.Item(
        hash_key=None,
        range_key=None,
        attrs={
            "Id": {"N": "8"},
            "Subs": {"N": "10"},
            "Des": {"S": "A description"},
            "KV": {"SS": ["test3", "test4"]},
        },
    )

    # NOT test 1
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "NOT attribute_not_exists(Id)", {}, {}
    )
    assert filter_expr.expr(row1) is True

    # NOT test 2
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "NOT (Id = :v0)", {}, {":v0": {"N": "8"}}
    )
    assert filter_expr.expr(row1) is False  # Id = 8 so should be false

    # AND test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id > :v0 AND Subs < :v1", {}, {":v0": {"N": "5"}, ":v1": {"N": "7"}}
    )
    assert filter_expr.expr(row1) is True
    assert filter_expr.expr(row2) is False

    # lowercase AND test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id > :v0 and Subs < :v1", {}, {":v0": {"N": "5"}, ":v1": {"N": "7"}}
    )
    assert filter_expr.expr(row1) is True
    assert filter_expr.expr(row2) is False

    # OR test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id = :v0 OR Id=:v1", {}, {":v0": {"N": "5"}, ":v1": {"N": "8"}}
    )
    assert filter_expr.expr(row1) is True

    # BETWEEN test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id BETWEEN :v0 AND :v1", {}, {":v0": {"N": "5"}, ":v1": {"N": "10"}}
    )
    assert filter_expr.expr(row1) is True

    # BETWEEN integer test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id BETWEEN :v0 AND :v1", {}, {":v0": {"N": "0"}, ":v1": {"N": "10"}}
    )
    assert filter_expr.expr(row1) is True

    # PAREN test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id = :v0 AND (Subs = :v0 OR Subs = :v1)",
        {},
        {":v0": {"N": "8"}, ":v1": {"N": "5"}},
    )
    assert filter_expr.expr(row1) is True

    # IN test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "Id IN (:v0, :v1, :v2)",
        {},
        {":v0": {"N": "7"}, ":v1": {"N": "8"}, ":v2": {"N": "9"}},
    )
    assert filter_expr.expr(row1) is True

    # attribute function tests (with extra spaces)
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "attribute_exists(Id) AND attribute_not_exists (UnknownAttribute)", {}, {}
    )
    assert filter_expr.expr(row1) is True

    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "attribute_type(Id, :v0)", {}, {":v0": {"S": "N"}}
    )
    assert filter_expr.expr(row1) is True

    # beginswith function test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "begins_with(Des, :v0)", {}, {":v0": {"S": "Some"}}
    )
    assert filter_expr.expr(row1) is True
    assert filter_expr.expr(row2) is False

    # contains function test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "contains(KV, :v0)", {}, {":v0": {"S": "test1"}}
    )
    assert filter_expr.expr(row1) is True
    assert filter_expr.expr(row2) is False

    # size function test
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "size(Des) > size(KV)", {}, {}
    )
    assert filter_expr.expr(row1) is True

    # Expression from @batkuip
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "(#n0 < :v0 AND attribute_not_exists(#n1))",
        {"#n0": "Subs", "#n1": "fanout_ts"},
        {":v0": {"N": "7"}},
    )
    assert filter_expr.expr(row1) is True
    # Expression from to check contains on string value
    filter_expr = moto.dynamodb.comparisons.get_filter_expression(
        "contains(#n0, :v0)", {"#n0": "Des"}, {":v0": {"S": "Some"}}
    )
    assert filter_expr.expr(row1) is True
    assert filter_expr.expr(row2) is False


@mock_aws
def test_duplicate_create():
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )

    with pytest.raises(ClientError) as exc:
        client.create_table(
            TableName="test1",
            AttributeDefinitions=[
                {"AttributeName": "client", "AttributeType": "S"},
                {"AttributeName": "app", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "client", "KeyType": "HASH"},
                {"AttributeName": "app", "KeyType": "RANGE"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
        )
    err = exc.value.response["Error"]
    assert err["Code"] == "ResourceInUseException"


@mock_aws
def test_delete_table():
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )

    client.delete_table(TableName="test1")

    resp = client.list_tables()
    assert len(resp["TableNames"]) == 0

    with pytest.raises(ClientError) as err:
        client.delete_table(TableName="test1")
    assert err.value.response["Error"]["Code"] == "ResourceNotFoundException"


@mock_aws
def test_delete_item():
    client = boto3.client("dynamodb", region_name="us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )
    client.put_item(
        TableName="test1", Item={"client": {"S": "client1"}, "app": {"S": "app1"}}
    )
    client.put_item(
        TableName="test1", Item={"client": {"S": "client1"}, "app": {"S": "app2"}}
    )

    table = dynamodb.Table("test1")
    response = table.scan()
    assert response["Count"] == 2

    # Test ReturnValues validation
    with pytest.raises(ClientError) as ex:
        table.delete_item(
            Key={"client": "client1", "app": "app1"}, ReturnValues="ALL_NEW"
        )
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert err["Message"] == "Return values set to invalid value"

    # Test deletion and returning old value
    response = table.delete_item(
        Key={"client": "client1", "app": "app1"}, ReturnValues="ALL_OLD"
    )
    assert "client" in response["Attributes"]
    assert "app" in response["Attributes"]

    response = table.scan()
    assert response["Count"] == 1

    # Test deletion returning nothing
    response = table.delete_item(Key={"client": "client1", "app": "app2"})
    assert len(response["Attributes"]) == 0

    response = table.scan()
    assert response["Count"] == 0


@mock_aws
def test_delete_item_error():
    # Setup
    client = boto3.resource("dynamodb", region_name="us-east-1")
    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table = client.Table("test1")
    table.delete()

    # Execute
    with pytest.raises(ClientError) as ex:
        table.delete_item(
            Key={"client": "client1", "app": "app1"},
        )

    # Verify
    err = ex.value.response["Error"]
    assert err["Code"] == "ResourceNotFoundException"
    assert err["Message"] == "Requested resource not found"


@mock_aws
def test_describe_limits():
    client = boto3.client("dynamodb", region_name="eu-central-1")
    resp = client.describe_limits()

    assert resp["AccountMaxReadCapacityUnits"] == 20000
    assert resp["AccountMaxWriteCapacityUnits"] == 20000
    assert resp["TableMaxWriteCapacityUnits"] == 10000
    assert resp["TableMaxReadCapacityUnits"] == 10000


@mock_aws
def test_set_ttl():
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )

    client.update_time_to_live(
        TableName="test1",
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "expire"},
    )

    resp = client.describe_time_to_live(TableName="test1")
    assert resp["TimeToLiveDescription"]["TimeToLiveStatus"] == "ENABLED"
    assert resp["TimeToLiveDescription"]["AttributeName"] == "expire"

    client.update_time_to_live(
        TableName="test1",
        TimeToLiveSpecification={"Enabled": False, "AttributeName": "expire"},
    )

    resp = client.describe_time_to_live(TableName="test1")
    assert resp["TimeToLiveDescription"]["TimeToLiveStatus"] == "DISABLED"


@mock_aws
def test_describe_continuous_backups():
    # given
    client = boto3.client("dynamodb", region_name="us-east-1")
    table_name = client.create_table(
        TableName="test",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )["TableDescription"]["TableName"]

    # when
    response = client.describe_continuous_backups(TableName=table_name)

    # then
    assert response["ContinuousBackupsDescription"] == {
        "ContinuousBackupsStatus": "ENABLED",
        "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"},
    }


@mock_aws
def test_describe_continuous_backups_errors():
    # given
    client = boto3.client("dynamodb", region_name="us-east-1")

    # when
    with pytest.raises(ClientError) as e:
        client.describe_continuous_backups(TableName="not-existing-table")

    # then
    ex = e.value
    assert ex.operation_name == "DescribeContinuousBackups"
    assert ex.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert ex.response["Error"]["Code"] == "TableNotFoundException"
    assert ex.response["Error"]["Message"] == "Table not found: not-existing-table"


@mock_aws
def test_update_continuous_backups():
    # given
    client = boto3.client("dynamodb", region_name="us-east-1")
    table_name = client.create_table(
        TableName="test",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )["TableDescription"]["TableName"]

    # when
    response = client.update_continuous_backups(
        TableName=table_name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )

    # then
    assert (
        response["ContinuousBackupsDescription"]["ContinuousBackupsStatus"] == "ENABLED"
    )
    point_in_time = response["ContinuousBackupsDescription"][
        "PointInTimeRecoveryDescription"
    ]
    earliest_datetime = point_in_time["EarliestRestorableDateTime"]
    assert isinstance(earliest_datetime, datetime)
    latest_datetime = point_in_time["LatestRestorableDateTime"]
    assert isinstance(latest_datetime, datetime)
    assert point_in_time["PointInTimeRecoveryStatus"] == "ENABLED"

    # when
    # a second update should not change anything
    response = client.update_continuous_backups(
        TableName=table_name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )

    # then
    assert (
        response["ContinuousBackupsDescription"]["ContinuousBackupsStatus"] == "ENABLED"
    )
    point_in_time = response["ContinuousBackupsDescription"][
        "PointInTimeRecoveryDescription"
    ]
    assert point_in_time["EarliestRestorableDateTime"] == earliest_datetime
    assert point_in_time["LatestRestorableDateTime"] == latest_datetime
    assert point_in_time["PointInTimeRecoveryStatus"] == "ENABLED"

    # when
    response = client.update_continuous_backups(
        TableName=table_name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": False},
    )

    # then
    assert response["ContinuousBackupsDescription"] == {
        "ContinuousBackupsStatus": "ENABLED",
        "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"},
    }


@mock_aws
def test_update_continuous_backups_errors():
    # given
    client = boto3.client("dynamodb", region_name="us-east-1")

    # when
    with pytest.raises(ClientError) as e:
        client.update_continuous_backups(
            TableName="not-existing-table",
            PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
        )

    # then
    ex = e.value
    assert ex.operation_name == "UpdateContinuousBackups"
    assert ex.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert ex.response["Error"]["Code"] == "TableNotFoundException"
    assert ex.response["Error"]["Message"] == "Table not found: not-existing-table"


# https://github.com/getmoto/moto/issues/1043
@mock_aws
def test_query_missing_expr_names():
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    client.create_table(
        TableName="test1",
        AttributeDefinitions=[
            {"AttributeName": "client", "AttributeType": "S"},
            {"AttributeName": "app", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "client", "KeyType": "HASH"},
            {"AttributeName": "app", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 123, "WriteCapacityUnits": 123},
    )
    client.put_item(
        TableName="test1", Item={"client": {"S": "test1"}, "app": {"S": "test1"}}
    )
    client.put_item(
        TableName="test1", Item={"client": {"S": "test2"}, "app": {"S": "test2"}}
    )

    resp = client.query(
        TableName="test1",
        KeyConditionExpression="client=:client",
        ExpressionAttributeValues={":client": {"S": "test1"}},
    )

    assert resp["Count"] == 1
    assert resp["Items"][0]["client"]["S"] == "test1"


# https://github.com/getmoto/moto/issues/2328
@mock_aws
def test_update_item_with_list():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="Table",
        KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamodb.Table("Table")
    table.update_item(
        Key={"key": "the-key"},
        AttributeUpdates={"list": {"Value": [1, 2], "Action": "PUT"}},
    )

    resp = table.get_item(Key={"key": "the-key"})
    assert resp["Item"] == {"key": "the-key", "list": [1, 2]}


# https://github.com/getmoto/moto/issues/2328
@mock_aws
def test_update_item_with_no_action_passed_with_list():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="Table",
        KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamodb.Table("Table")
    table.update_item(
        Key={"key": "the-key"},
        # Do not pass 'Action' key, in order to check that the
        # parameter's default value will be used.
        AttributeUpdates={"list": {"Value": [1, 2]}},
    )

    resp = table.get_item(Key={"key": "the-key"})
    assert resp["Item"] == {"key": "the-key", "list": [1, 2]}


# https://github.com/getmoto/moto/issues/1342
@mock_aws
def test_update_item_on_map():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    client = boto3.client("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(
        Item={
            "forum_name": "the-key",
            "subject": "123",
            "body": {"nested": {"data": "test"}},
        }
    )

    resp = table.scan()
    assert resp["Items"][0]["body"] == {"nested": {"data": "test"}}

    # Nonexistent nested attributes are supported for existing top-level attributes.
    table.update_item(
        Key={"forum_name": "the-key", "subject": "123"},
        UpdateExpression="SET body.#nested.#data = :tb",
        ExpressionAttributeNames={"#nested": "nested", "#data": "data"},
        ExpressionAttributeValues={":tb": "new_value"},
    )
    # Running this against AWS DDB gives an exception so make sure it also fails.:
    with pytest.raises(client.exceptions.ClientError):
        # botocore.exceptions.ClientError: An error occurred (ValidationException) when calling the UpdateItem
        # operation: The document path provided in the update expression is invalid for update
        table.update_item(
            Key={"forum_name": "the-key", "subject": "123"},
            UpdateExpression="SET body.#nested.#nonexistentnested.#data = :tb2",
            ExpressionAttributeNames={
                "#nested": "nested",
                "#nonexistentnested": "nonexistentnested",
                "#data": "data",
            },
            ExpressionAttributeValues={":tb2": "other_value"},
        )

    table.update_item(
        Key={"forum_name": "the-key", "subject": "123"},
        UpdateExpression="SET body.#nested.#nonexistentnested = :tb2",
        ExpressionAttributeNames={
            "#nested": "nested",
            "#nonexistentnested": "nonexistentnested",
        },
        ExpressionAttributeValues={":tb2": {"data": "other_value"}},
    )

    resp = table.scan()
    assert resp["Items"][0]["body"] == {
        "nested": {"data": "new_value", "nonexistentnested": {"data": "other_value"}}
    }

    # Test nested value for a nonexistent attribute throws a ClientError.
    with pytest.raises(client.exceptions.ClientError):
        table.update_item(
            Key={"forum_name": "the-key", "subject": "123"},
            UpdateExpression="SET nonexistent.#nested = :tb",
            ExpressionAttributeNames={"#nested": "nested"},
            ExpressionAttributeValues={":tb": "new_value"},
        )


# https://github.com/getmoto/moto/issues/1358
@mock_aws
def test_update_if_not_exists():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "forum_name", "KeyType": "HASH"},
            {"AttributeName": "subject", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "forum_name", "AttributeType": "S"},
            {"AttributeName": "subject", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")

    table.put_item(Item={"forum_name": "the-key", "subject": "123"})

    table.update_item(
        Key={"forum_name": "the-key", "subject": "123"},
        # if_not_exists without space
        UpdateExpression="SET created_at=if_not_exists(created_at,:created_at)",
        ExpressionAttributeValues={":created_at": 123},
    )

    resp = table.scan()
    assert resp["Items"][0]["created_at"] == 123

    table.update_item(
        Key={"forum_name": "the-key", "subject": "123"},
        # if_not_exists with space
        UpdateExpression="SET created_at = if_not_exists (created_at, :created_at)",
        ExpressionAttributeValues={":created_at": 456},
    )

    resp = table.scan()
    # Still the original value
    assert resp["Items"][0]["created_at"] == 123


# https://github.com/getmoto/moto/issues/1937
@mock_aws
def test_update_return_attributes():
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")

    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )

    def update(col, to, rv):
        return dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "foo"}},
            AttributeUpdates={col: {"Value": {"S": to}, "Action": "PUT"}},
            ReturnValues=rv,
        )

    r = update("col1", "val1", "ALL_NEW")
    assert r["Attributes"] == {"id": {"S": "foo"}, "col1": {"S": "val1"}}

    r = update("col1", "val2", "ALL_OLD")
    assert r["Attributes"] == {"id": {"S": "foo"}, "col1": {"S": "val1"}}

    r = update("col2", "val3", "UPDATED_NEW")
    assert r["Attributes"] == {"col2": {"S": "val3"}}

    r = update("col2", "val4", "UPDATED_OLD")
    assert r["Attributes"] == {"col2": {"S": "val3"}}

    r = update("col1", "val5", "NONE")
    assert r["Attributes"] == {}

    with pytest.raises(ClientError) as ex:
        update("col1", "val6", "WRONG")
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert err["Message"] == "Return values set to invalid value"


# https://github.com/getmoto/moto/issues/3448
@mock_aws
def test_update_return_updated_new_attributes_when_same():
    dynamo_client = boto3.resource("dynamodb", region_name="us-east-1")
    dynamo_client.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "HashKey1", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "HashKey1", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )

    dynamodb_table = dynamo_client.Table("moto-test")
    dynamodb_table.put_item(
        Item={"HashKey1": "HashKeyValue1", "listValuedAttribute1": ["a", "b"]}
    )

    def update(col, to, rv):
        return dynamodb_table.update_item(
            TableName="moto-test",
            Key={"HashKey1": "HashKeyValue1"},
            UpdateExpression="SET listValuedAttribute1=:" + col,
            ExpressionAttributeValues={":" + col: to},
            ReturnValues=rv,
        )

    r = update("a", ["a", "c"], "UPDATED_NEW")
    assert r["Attributes"] == {"listValuedAttribute1": ["a", "c"]}

    r = update("a", {"a", "c"}, "UPDATED_NEW")
    assert r["Attributes"] == {"listValuedAttribute1": {"a", "c"}}

    r = update("a", {1, 2}, "UPDATED_NEW")
    assert r["Attributes"] == {"listValuedAttribute1": {1, 2}}

    with pytest.raises(ClientError) as ex:
        update("a", ["a", "c"], "WRONG")
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert err["Message"] == "Return values set to invalid value"


@mock_aws
def test_put_return_attributes():
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")

    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )

    r = dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "foo"}, "col1": {"S": "val1"}},
        ReturnValues="NONE",
    )
    assert "Attributes" not in r

    r = dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "foo"}, "col1": {"S": "val2"}},
        ReturnValues="ALL_OLD",
    )
    assert r["Attributes"] == {"id": {"S": "foo"}, "col1": {"S": "val1"}}

    with pytest.raises(ClientError) as ex:
        dynamodb.put_item(
            TableName="moto-test",
            Item={"id": {"S": "foo"}, "col1": {"S": "val3"}},
            ReturnValues="ALL_NEW",
        )
    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert ex.value.response["Error"]["Message"] == "Return values set to invalid value"


@mock_aws
def test_query_global_secondary_index_when_created_via_update_table_resource():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table.
    dynamodb.create_table(
        TableName="users",
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "N"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = dynamodb.Table("users")
    table.update(
        AttributeDefinitions=[{"AttributeName": "forum_name", "AttributeType": "S"}],
        GlobalSecondaryIndexUpdates=[
            {
                "Create": {
                    "IndexName": "forum_name_index",
                    "KeySchema": [{"AttributeName": "forum_name", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 5,
                        "WriteCapacityUnits": 5,
                    },
                }
            }
        ],
    )

    next_user_id = 1
    for my_forum_name in ["cats", "dogs"]:
        for my_subject in [
            "my pet is the cutest",
            "wow look at what my pet did",
            "don't you love my pet?",
        ]:
            table.put_item(
                Item={
                    "user_id": next_user_id,
                    "forum_name": my_forum_name,
                    "subject": my_subject,
                }
            )
            next_user_id += 1

    # get all the cat users
    forum_only_query_response = table.query(
        IndexName="forum_name_index",
        Select="ALL_ATTRIBUTES",
        KeyConditionExpression=Key("forum_name").eq("cats"),
    )
    forum_only_items = forum_only_query_response["Items"]
    assert len(forum_only_items) == 3
    for item in forum_only_items:
        assert item["forum_name"] == "cats"

    # query all cat users with a particular subject
    forum_and_subject_query_results = table.query(
        IndexName="forum_name_index",
        Select="ALL_ATTRIBUTES",
        KeyConditionExpression=Key("forum_name").eq("cats"),
        FilterExpression=Attr("subject").eq("my pet is the cutest"),
    )
    forum_and_subject_items = forum_and_subject_query_results["Items"]
    assert len(forum_and_subject_items) == 1
    assert forum_and_subject_items[0] == {
        "user_id": Decimal("1"),
        "forum_name": "cats",
        "subject": "my pet is the cutest",
    }


@mock_aws
def test_scan_by_non_exists_index():
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")

    dynamodb.create_table(
        TableName="test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "gsi_col", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_gsi",
                "KeySchema": [{"AttributeName": "gsi_col", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
    )

    with pytest.raises(ClientError) as ex:
        dynamodb.scan(TableName="test", IndexName="non_exists_index")

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "The table does not have the specified index: non_exists_index"
    )


@mock_aws
def test_query_by_non_exists_index():
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")

    dynamodb.create_table(
        TableName="test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "gsi_col", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_gsi",
                "KeySchema": [{"AttributeName": "gsi_col", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
    )

    with pytest.raises(ClientError) as ex:
        dynamodb.query(
            TableName="test",
            IndexName="non_exists_index",
            KeyConditionExpression="CarModel=M",
        )

    assert ex.value.response["Error"]["Code"] == "ResourceNotFoundException"
    assert (
        ex.value.response["Error"]["Message"]
        == "Invalid index: non_exists_index for table: test. Available indexes are: test_gsi"
    )


@mock_aws
def test_index_with_unknown_attributes_should_fail():
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")

    expected_exception = (
        "Some index key attributes are not defined in AttributeDefinitions."
    )

    with pytest.raises(ClientError) as ex:
        dynamodb.create_table(
            AttributeDefinitions=[
                {"AttributeName": "customer_nr", "AttributeType": "S"},
                {"AttributeName": "last_name", "AttributeType": "S"},
            ],
            TableName="table_with_missing_attribute_definitions",
            KeySchema=[
                {"AttributeName": "customer_nr", "KeyType": "HASH"},
                {"AttributeName": "last_name", "KeyType": "RANGE"},
            ],
            LocalSecondaryIndexes=[
                {
                    "IndexName": "indexthataddsanadditionalattribute",
                    "KeySchema": [
                        {"AttributeName": "customer_nr", "KeyType": "HASH"},
                        {"AttributeName": "postcode", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert expected_exception in ex.value.response["Error"]["Message"]


@mock_aws
def test_update_list_index__set_existing_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo"},
            "itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]},
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo"}},
        UpdateExpression="set itemlist[1]=:Item",
        ExpressionAttributeValues={":Item": {"S": "bar2_update"}},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo"}})["Item"]
    assert result["id"] == {"S": "foo"}
    assert result["itemlist"] == {
        "L": [{"S": "bar1"}, {"S": "bar2_update"}, {"S": "bar3"}]
    }


@mock_aws
def test_update_list_index__set_existing_nested_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo2"},
            "itemmap": {
                "M": {"itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]}}
            },
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo2"}},
        UpdateExpression="set itemmap.itemlist[1]=:Item",
        ExpressionAttributeValues={":Item": {"S": "bar2_update"}},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]
    assert result["id"] == {"S": "foo2"}
    assert result["itemmap"]["M"]["itemlist"]["L"] == [
        {"S": "bar1"},
        {"S": "bar2_update"},
        {"S": "bar3"},
    ]


@mock_aws
def test_update_list_index__set_index_out_of_range():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo"},
            "itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]},
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo"}},
        UpdateExpression="set itemlist[10]=:Item",
        ExpressionAttributeValues={":Item": {"S": "bar10"}},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo"}})["Item"]
    assert result["id"] == {"S": "foo"}
    assert result["itemlist"] == {
        "L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}, {"S": "bar10"}]
    }


@mock_aws
def test_update_list_index__set_nested_index_out_of_range():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo2"},
            "itemmap": {
                "M": {"itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]}}
            },
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo2"}},
        UpdateExpression="set itemmap.itemlist[10]=:Item",
        ExpressionAttributeValues={":Item": {"S": "bar10"}},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]
    assert result["id"] == {"S": "foo2"}
    assert result["itemmap"]["M"]["itemlist"]["L"] == [
        {"S": "bar1"},
        {"S": "bar2"},
        {"S": "bar3"},
        {"S": "bar10"},
    ]


@mock_aws
def test_update_list_index__set_double_nested_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo2"},
            "itemmap": {
                "M": {
                    "itemlist": {
                        "L": [
                            {"M": {"foo": {"S": "bar11"}, "foos": {"S": "bar12"}}},
                            {"M": {"foo": {"S": "bar21"}, "foos": {"S": "bar21"}}},
                        ]
                    }
                }
            },
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo2"}},
        UpdateExpression="set itemmap.itemlist[1].foos=:Item",
        ExpressionAttributeValues={":Item": {"S": "bar22"}},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]
    assert result["id"] == {"S": "foo2"}
    assert len(result["itemmap"]["M"]["itemlist"]["L"]) == 2
    assert result["itemmap"]["M"]["itemlist"]["L"][0] == {
        "M": {"foo": {"S": "bar11"}, "foos": {"S": "bar12"}}
    }  # unchanged
    assert result["itemmap"]["M"]["itemlist"]["L"][1] == {
        "M": {"foo": {"S": "bar21"}, "foos": {"S": "bar22"}}
    }  # updated


@mock_aws
def test_update_list_index__set_index_of_a_string():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name, Item={"id": {"S": "foo2"}, "itemstr": {"S": "somestring"}}
    )
    with pytest.raises(ClientError) as ex:
        client.update_item(
            TableName=table_name,
            Key={"id": {"S": "foo2"}},
            UpdateExpression="set itemstr[1]=:Item",
            ExpressionAttributeValues={":Item": {"S": "string_update"}},
        )
        client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert (
        ex.value.response["Error"]["Message"]
        == "The document path provided in the update expression is invalid for update"
    )


@mock_aws
def test_remove_top_level_attribute():
    table_name = "test_remove"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name, Item={"id": {"S": "foo"}, "item": {"S": "bar"}}
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo"}},
        UpdateExpression="REMOVE #i",
        ExpressionAttributeNames={"#i": "item"},
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo"}})["Item"]
    assert result == {"id": {"S": "foo"}}


@pytest.mark.aws_verified
@dynamodb_aws_verified()
def test_remove_top_level_attribute_non_existent(table_name=None):
    """
    Remove statements do not require attribute to exist they silently pass
    """
    client = boto3.client("dynamodb", "us-east-1")
    ddb_item = {"pk": {"S": "foo"}, "item": {"S": "bar"}}
    client.put_item(TableName=table_name, Item=ddb_item)
    client.update_item(
        TableName=table_name,
        Key={"pk": {"S": "foo"}},
        UpdateExpression="REMOVE non_existent_attribute",
    )
    result = client.get_item(TableName=table_name, Key={"pk": {"S": "foo"}})["Item"]
    assert result == ddb_item


@mock_aws
def test_remove_list_index__remove_existing_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo"},
            "itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]},
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo"}},
        UpdateExpression="REMOVE itemlist[1]",
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo"}})["Item"]
    assert result["id"] == {"S": "foo"}
    assert result["itemlist"] == {"L": [{"S": "bar1"}, {"S": "bar3"}]}


@mock_aws
def test_remove_list_index__remove_multiple_indexes():
    table_name = "remove-test"
    create_table_with_list(table_name)
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    table = dynamodb.Table(table_name)
    table.put_item(
        Item={
            "id": "woop",
            "bla": ["1", "2", "3", "4", "5"],
        },
    )

    table.update_item(
        Key={"id": "woop"}, UpdateExpression="REMOVE bla[0], bla[1], bla[2]"
    )

    result = table.get_item(Key={"id": "woop"})
    item = result["Item"]
    assert item["bla"] == ["4", "5"]


@mock_aws
def test_remove_list_index__remove_existing_nested_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo2"},
            "itemmap": {"M": {"itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}},
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo2"}},
        UpdateExpression="REMOVE itemmap.itemlist[1]",
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]
    assert result["id"] == {"S": "foo2"}
    assert result["itemmap"]["M"]["itemlist"]["L"] == [{"S": "bar1"}]


@mock_aws
def test_remove_list_index__remove_existing_double_nested_index():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo2"},
            "itemmap": {
                "M": {
                    "itemlist": {
                        "L": [
                            {"M": {"foo00": {"S": "bar1"}, "foo01": {"S": "bar2"}}},
                            {"M": {"foo10": {"S": "bar1"}, "foo11": {"S": "bar2"}}},
                        ]
                    }
                }
            },
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo2"}},
        UpdateExpression="REMOVE itemmap.itemlist[1].foo10",
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo2"}})["Item"]
    assert result["id"] == {"S": "foo2"}
    # untouched
    assert result["itemmap"]["M"]["itemlist"]["L"][0]["M"] == {
        "foo00": {"S": "bar1"},
        "foo01": {"S": "bar2"},
    }
    # changed
    assert result["itemmap"]["M"]["itemlist"]["L"][1]["M"] == {"foo11": {"S": "bar2"}}


@mock_aws
def test_remove_list_index__remove_index_out_of_range():
    table_name = "test_list_index_access"
    client = create_table_with_list(table_name)
    client.put_item(
        TableName=table_name,
        Item={
            "id": {"S": "foo"},
            "itemlist": {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]},
        },
    )
    client.update_item(
        TableName=table_name,
        Key={"id": {"S": "foo"}},
        UpdateExpression="REMOVE itemlist[10]",
    )
    #
    result = client.get_item(TableName=table_name, Key={"id": {"S": "foo"}})["Item"]
    assert result["id"] == {"S": "foo"}
    assert result["itemlist"] == {"L": [{"S": "bar1"}, {"S": "bar2"}, {"S": "bar3"}]}


def create_table_with_list(table_name):
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return client


# https://github.com/getmoto/moto/issues/1874
@mock_aws
def test_item_size_is_under_400KB():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    client = boto3.client("dynamodb", region_name="us-east-1")

    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamodb.Table("moto-test")

    large_item = "x" * 410 * 1000
    assert_failure_due_to_item_size(
        func=client.put_item,
        TableName="moto-test",
        Item={"id": {"S": "foo"}, "cont": {"S": large_item}},
    )
    assert_failure_due_to_item_size(
        func=table.put_item, Item={"id": "bar", "cont": large_item}
    )
    assert_failure_due_to_item_size_to_update(
        func=client.update_item,
        TableName="moto-test",
        Key={"id": {"S": "foo2"}},
        UpdateExpression="set cont=:Item",
        ExpressionAttributeValues={":Item": {"S": large_item}},
    )
    # Assert op fails when updating a nested item
    assert_failure_due_to_item_size(
        func=table.put_item, Item={"id": "bar", "itemlist": [{"cont": large_item}]}
    )
    assert_failure_due_to_item_size(
        func=client.put_item,
        TableName="moto-test",
        Item={
            "id": {"S": "foo"},
            "itemlist": {"L": [{"M": {"item1": {"S": large_item}}}]},
        },
    )


def assert_failure_due_to_item_size(func, **kwargs):
    with pytest.raises(ClientError) as ex:
        func(**kwargs)
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert err["Message"] == "Item size has exceeded the maximum allowed size"


def assert_failure_due_to_item_size_to_update(func, **kwargs):
    with pytest.raises(ClientError) as ex:
        func(**kwargs)
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert err["Message"] == "Item size to update has exceeded the maximum allowed size"


@mock_aws
def test_update_supports_complex_expression_attribute_values():
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        AttributeDefinitions=[{"AttributeName": "SHA256", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "SHA256", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    client.update_item(
        TableName="TestTable",
        Key={"SHA256": {"S": "sha-of-file"}},
        UpdateExpression=("SET MD5 = :md5,MyStringSet = :string_set,MyMap = :map"),
        ExpressionAttributeValues={
            ":md5": {"S": "md5-of-file"},
            ":string_set": {"SS": ["string1", "string2"]},
            ":map": {"M": {"EntryKey": {"SS": ["thing1", "thing2"]}}},
        },
    )
    result = client.get_item(
        TableName="TestTable", Key={"SHA256": {"S": "sha-of-file"}}
    )["Item"]
    assert result == {
        "MyStringSet": {"SS": ["string1", "string2"]},
        "MyMap": {"M": {"EntryKey": {"SS": ["thing1", "thing2"]}}},
        "SHA256": {"S": "sha-of-file"},
        "MD5": {"S": "md5-of-file"},
    }


@mock_aws
def test_update_supports_list_append():
    # Verify whether the list_append operation works as expected
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        AttributeDefinitions=[{"AttributeName": "SHA256", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "SHA256", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.put_item(
        TableName="TestTable",
        Item={"SHA256": {"S": "sha-of-file"}, "crontab": {"L": [{"S": "bar1"}]}},
    )

    # Update item using list_append expression
    updated_item = client.update_item(
        TableName="TestTable",
        Key={"SHA256": {"S": "sha-of-file"}},
        UpdateExpression="SET crontab = list_append(crontab, :i)",
        ExpressionAttributeValues={":i": {"L": [{"S": "bar2"}]}},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "crontab": {"L": [{"S": "bar1"}, {"S": "bar2"}]}
    }
    # Verify item is appended to the existing list
    result = client.get_item(
        TableName="TestTable", Key={"SHA256": {"S": "sha-of-file"}}
    )["Item"]
    assert result == {
        "SHA256": {"S": "sha-of-file"},
        "crontab": {"L": [{"S": "bar1"}, {"S": "bar2"}]},
    }


@mock_aws
def test_update_supports_nested_list_append():
    # Verify whether we can append a list that's inside a map
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.put_item(
        TableName="TestTable",
        Item={
            "id": {"S": "nested_list_append"},
            "a": {"M": {"b": {"L": [{"S": "bar1"}]}}},
        },
    )

    # Update item using list_append expression
    updated_item = client.update_item(
        TableName="TestTable",
        Key={"id": {"S": "nested_list_append"}},
        UpdateExpression="SET a.#b = list_append(a.#b, :i)",
        ExpressionAttributeValues={":i": {"L": [{"S": "bar2"}]}},
        ExpressionAttributeNames={"#b": "b"},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "a": {"M": {"b": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}}
    }
    result = client.get_item(
        TableName="TestTable", Key={"id": {"S": "nested_list_append"}}
    )["Item"]
    assert result == {
        "id": {"S": "nested_list_append"},
        "a": {"M": {"b": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}},
    }


@mock_aws
def test_update_supports_multiple_levels_nested_list_append():
    # Verify whether we can append a list that's inside a map that's inside a map  (Inception!)
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.put_item(
        TableName="TestTable",
        Item={
            "id": {"S": "nested_list_append"},
            "a": {"M": {"b": {"M": {"c": {"L": [{"S": "bar1"}]}}}}},
        },
    )

    # Update item using list_append expression
    updated_item = client.update_item(
        TableName="TestTable",
        Key={"id": {"S": "nested_list_append"}},
        UpdateExpression="SET a.#b.c = list_append(a.#b.#c, :i)",
        ExpressionAttributeValues={":i": {"L": [{"S": "bar2"}]}},
        ExpressionAttributeNames={"#b": "b", "#c": "c"},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "a": {"M": {"b": {"M": {"c": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}}}}
    }
    # Verify item is appended to the existing list
    result = client.get_item(
        TableName="TestTable", Key={"id": {"S": "nested_list_append"}}
    )["Item"]
    assert result == {
        "id": {"S": "nested_list_append"},
        "a": {"M": {"b": {"M": {"c": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}}}},
    }


@mock_aws
def test_update_supports_nested_list_append_onto_another_list():
    # Verify whether we can take the contents of one list, and use that to fill another list
    # Note that the contents of the other list is completely overwritten
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.put_item(
        TableName="TestTable",
        Item={
            "id": {"S": "list_append_another"},
            "a": {"M": {"b": {"L": [{"S": "bar1"}]}, "c": {"L": [{"S": "car1"}]}}},
        },
    )

    # Update item using list_append expression
    updated_item = client.update_item(
        TableName="TestTable",
        Key={"id": {"S": "list_append_another"}},
        UpdateExpression="SET a.#c = list_append(a.#b, :i)",
        ExpressionAttributeValues={":i": {"L": [{"S": "bar2"}]}},
        ExpressionAttributeNames={"#b": "b", "#c": "c"},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "a": {"M": {"c": {"L": [{"S": "bar1"}, {"S": "bar2"}]}}}
    }
    # Verify item is appended to the existing list
    result = client.get_item(
        TableName="TestTable", Key={"id": {"S": "list_append_another"}}
    )["Item"]
    assert result == {
        "id": {"S": "list_append_another"},
        "a": {
            "M": {
                "b": {"L": [{"S": "bar1"}]},
                "c": {"L": [{"S": "bar1"}, {"S": "bar2"}]},
            }
        },
    }


@mock_aws
def test_update_supports_list_append_maps():
    client = boto3.client("dynamodb", region_name="us-west-1")
    client.create_table(
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "rid", "AttributeType": "S"},
        ],
        TableName="TestTable",
        KeySchema=[
            {"AttributeName": "id", "KeyType": "HASH"},
            {"AttributeName": "rid", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.put_item(
        TableName="TestTable",
        Item={
            "id": {"S": "nested_list_append"},
            "rid": {"S": "range_key"},
            "a": {"L": [{"M": {"b": {"S": "bar1"}}}]},
        },
    )

    # Update item using list_append expression
    updated_item = client.update_item(
        TableName="TestTable",
        Key={"id": {"S": "nested_list_append"}, "rid": {"S": "range_key"}},
        UpdateExpression="SET a = list_append(a, :i)",
        ExpressionAttributeValues={":i": {"L": [{"M": {"b": {"S": "bar2"}}}]}},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "a": {"L": [{"M": {"b": {"S": "bar1"}}}, {"M": {"b": {"S": "bar2"}}}]}
    }
    # Verify item is appended to the existing list
    result = client.query(
        TableName="TestTable",
        KeyConditionExpression="id = :i AND begins_with(rid, :r)",
        ExpressionAttributeValues={
            ":i": {"S": "nested_list_append"},
            ":r": {"S": "range_key"},
        },
    )["Items"]
    assert result == [
        {
            "a": {"L": [{"M": {"b": {"S": "bar1"}}}, {"M": {"b": {"S": "bar2"}}}]},
            "rid": {"S": "range_key"},
            "id": {"S": "nested_list_append"},
        }
    ]


@mock_aws
def test_update_supports_nested_update_if_nested_value_not_exists():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    name = "TestTable"

    dynamodb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    table = dynamodb.Table(name)
    table.put_item(
        Item={"user_id": "1234", "friends": {"5678": {"name": "friend_5678"}}}
    )
    table.update_item(
        Key={"user_id": "1234"},
        ExpressionAttributeNames={"#friends": "friends", "#friendid": "0000"},
        ExpressionAttributeValues={":friend": {"name": "friend_0000"}},
        UpdateExpression="SET #friends.#friendid = :friend",
        ReturnValues="UPDATED_NEW",
    )
    item = table.get_item(Key={"user_id": "1234"})["Item"]
    assert item == {
        "user_id": "1234",
        "friends": {"5678": {"name": "friend_5678"}, "0000": {"name": "friend_0000"}},
    }


@mock_aws
def test_update_supports_list_append_with_nested_if_not_exists_operation():
    dynamo = boto3.resource("dynamodb", region_name="us-west-1")
    table_name = "test"

    dynamo.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": "Id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "Id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 20, "WriteCapacityUnits": 20},
    )

    table = dynamo.Table(table_name)

    table.put_item(Item={"Id": "item-id", "nest1": {"nest2": {}}})
    updated_item = table.update_item(
        Key={"Id": "item-id"},
        UpdateExpression="SET nest1.nest2.event_history = list_append(if_not_exists(nest1.nest2.event_history, :empty_list), :new_value)",
        ExpressionAttributeValues={":empty_list": [], ":new_value": ["some_value"]},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "nest1": {"nest2": {"event_history": ["some_value"]}}
    }

    assert table.get_item(Key={"Id": "item-id"})["Item"] == {
        "Id": "item-id",
        "nest1": {"nest2": {"event_history": ["some_value"]}},
    }


@mock_aws
def test_update_supports_list_append_with_nested_if_not_exists_operation_and_property_already_exists():
    dynamo = boto3.resource("dynamodb", region_name="us-west-1")
    table_name = "test"

    dynamo.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": "Id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "Id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 20, "WriteCapacityUnits": 20},
    )

    table = dynamo.Table(table_name)

    table.put_item(Item={"Id": "item-id", "event_history": ["other_value"]})
    updated_item = table.update_item(
        Key={"Id": "item-id"},
        UpdateExpression="SET event_history = list_append(if_not_exists(event_history, :empty_list), :new_value)",
        ExpressionAttributeValues={":empty_list": [], ":new_value": ["some_value"]},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {
        "event_history": ["other_value", "some_value"]
    }

    assert table.get_item(Key={"Id": "item-id"})["Item"] == {
        "Id": "item-id",
        "event_history": ["other_value", "some_value"],
    }


@mock_aws
def test_update_item_if_original_value_is_none():
    dynamo = boto3.resource("dynamodb", region_name="eu-central-1")
    dynamo.create_table(
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        TableName="origin-rbu-dev",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamo.Table("origin-rbu-dev")
    table.put_item(Item={"job_id": "a", "job_name": None})
    table.update_item(
        Key={"job_id": "a"},
        UpdateExpression="SET job_name = :output",
        ExpressionAttributeValues={":output": "updated"},
    )
    assert table.scan()["Items"][0]["job_name"] == "updated"


@mock_aws
def test_update_nested_item_if_original_value_is_none():
    dynamo = boto3.resource("dynamodb", region_name="eu-central-1")
    dynamo.create_table(
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        TableName="origin-rbu-dev",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamo.Table("origin-rbu-dev")
    table.put_item(Item={"job_id": "a", "job_details": {"job_name": None}})
    updated_item = table.update_item(
        Key={"job_id": "a"},
        UpdateExpression="SET job_details.job_name = :output",
        ExpressionAttributeValues={":output": "updated"},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {"job_details": {"job_name": "updated"}}

    assert table.scan()["Items"][0]["job_details"]["job_name"] == "updated"


@mock_aws
def test_allow_update_to_item_with_different_type():
    dynamo = boto3.resource("dynamodb", region_name="eu-central-1")
    dynamo.create_table(
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        TableName="origin-rbu-dev",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamo.Table("origin-rbu-dev")
    table.put_item(Item={"job_id": "a", "job_details": {"job_name": {"nested": "yes"}}})
    table.put_item(Item={"job_id": "b", "job_details": {"job_name": {"nested": "yes"}}})
    updated_item = table.update_item(
        Key={"job_id": "a"},
        UpdateExpression="SET job_details.job_name = :output",
        ExpressionAttributeValues={":output": "updated"},
        ReturnValues="UPDATED_NEW",
    )

    # Verify updated item is correct
    assert updated_item["Attributes"] == {"job_details": {"job_name": "updated"}}

    assert (
        table.get_item(Key={"job_id": "a"})["Item"]["job_details"]["job_name"]
        == "updated"
    )
    assert table.get_item(Key={"job_id": "b"})["Item"]["job_details"]["job_name"] == {
        "nested": "yes"
    }


@mock_aws
def test_query_catches_when_no_filters():
    dynamo = boto3.resource("dynamodb", region_name="eu-central-1")
    dynamo.create_table(
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        TableName="origin-rbu-dev",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    table = dynamo.Table("origin-rbu-dev")

    with pytest.raises(ClientError) as ex:
        table.query(TableName="original-rbu-dev")

    assert ex.value.response["Error"]["Code"] == "ValidationException"
    assert ex.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert (
        ex.value.response["Error"]["Message"]
        == "Either KeyConditions or QueryFilter should be present"
    )


@mock_aws
def test_dynamodb_max_1mb_limit():
    ddb = boto3.resource("dynamodb", region_name="eu-west-1")

    table_name = "populated-mock-table"
    table = ddb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "partition_key", "KeyType": "HASH"},
            {"AttributeName": "sort_key", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "partition_key", "AttributeType": "S"},
            {"AttributeName": "sort_key", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Populate the table
    items = [
        {
            "partition_key": "partition_key_val",  # size=30
            "sort_key": "sort_key_value____" + str(i),  # size=30
        }
        for i in range(10000, 29999)
    ]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    response = table.query(
        KeyConditionExpression=Key("partition_key").eq("partition_key_val")
    )
    # We shouldn't get everything back - the total result set is well over 1MB
    assert len(items) > response["Count"]
    assert response["LastEvaluatedKey"] is not None


def assert_raise_syntax_error(client_error, token, near):
    """
    Assert whether a client_error is as expected Syntax error. Syntax error looks like: `syntax_error_template`

    Args:
        client_error(ClientError): The ClientError exception that was raised
        token(str): The token that ws unexpected
        near(str): The part in the expression that shows where the error occurs it generally has the preceding token the
        optional separation and the problematic token.
    """
    syntax_error_template = (
        'Invalid UpdateExpression: Syntax error; token: "{token}", near: "{near}"'
    )
    expected_syntax_error = syntax_error_template.format(token=token, near=near)
    assert client_error["Code"] == "ValidationException"
    assert expected_syntax_error == client_error["Message"]


@mock_aws
def test_update_expression_with_numeric_literal_instead_of_value():
    """
    DynamoDB requires literals to be passed in as values. If they are put literally in the expression a token error will
    be raised
    """
    dynamodb = boto3.client("dynamodb", region_name="eu-west-1")

    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    with pytest.raises(ClientError) as exc:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = myNum + 1",
        )
    err = exc.value.response["Error"]
    assert_raise_syntax_error(err, "1", "+ 1")


@mock_aws
def test_update_expression_with_multiple_set_clauses_must_be_comma_separated():
    """
    An UpdateExpression can have multiple set clauses but if they are passed in without the separating comma.
    """
    dynamodb = boto3.client("dynamodb", region_name="eu-west-1")

    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    with pytest.raises(ClientError) as exc:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = myNum Mystr2 myNum2",
        )
    err = exc.value.response["Error"]
    assert_raise_syntax_error(err, "Mystr2", "myNum Mystr2 myNum2")


@mock_aws
def test_list_tables_exclusive_start_table_name_empty():
    client = boto3.client("dynamodb", region_name="us-east-1")

    resp = client.list_tables(Limit=1, ExclusiveStartTableName="whatever")

    assert len(resp["TableNames"]) == 0


def assert_correct_client_error(
    client_error, code, message_template, message_values=None, braces=None
):
    """
    Assert whether a client_error is as expected. Allow for a list of values to be passed into the message

    Args:
        client_error(ClientError): The ClientError exception that was raised
        code(str): The code for the error (e.g. ValidationException)
        message_template(str): Error message template. if message_values is not None then this template has a {values}
            as placeholder. For example:
            'Value provided in ExpressionAttributeValues unused in expressions: keys: {values}'
        message_values(list of str|None): The values that are passed in the error message
        braces(list of str|None): List of length 2 with opening and closing brace for the values. By default it will be
                                  surrounded by curly brackets
    """
    braces = braces or ["{", "}"]
    assert client_error.response["Error"]["Code"] == code
    if message_values is not None:
        values_string = f"{braces[0]}(?P<values>.*){braces[1]}"
        re_msg = re.compile(message_template.format(values=values_string))
        match_result = re_msg.match(client_error.response["Error"]["Message"])
        assert match_result is not None
        values_string = match_result.groupdict()["values"]
        values = [key for key in values_string.split(", ")]
        assert len(message_values) == len(values)
        for value in message_values:
            assert value in values
    else:
        assert client_error.response["Error"]["Message"] == message_template


def create_simple_table_and_return_client():
    dynamodb = boto3.client("dynamodb", region_name="eu-west-1")
    dynamodb.create_table(
        TableName="moto-test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "myNum": {"N": "1"}, "MyStr": {"S": "1"}},
    )
    return dynamodb


# https://github.com/getmoto/moto/issues/2806
# https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_UpdateItem.html
#       #DDB-UpdateItem-request-UpdateExpression
@mock_aws
def test_update_item_with_attribute_in_right_hand_side_and_operation():
    dynamodb = create_simple_table_and_return_client()

    dynamodb.update_item(
        TableName="moto-test",
        Key={"id": {"S": "1"}},
        UpdateExpression="SET myNum = myNum+:val",
        ExpressionAttributeValues={":val": {"N": "3"}},
    )

    result = dynamodb.get_item(TableName="moto-test", Key={"id": {"S": "1"}})
    assert result["Item"]["myNum"]["N"] == "4"

    dynamodb.update_item(
        TableName="moto-test",
        Key={"id": {"S": "1"}},
        UpdateExpression="SET myNum = myNum - :val",
        ExpressionAttributeValues={":val": {"N": "1"}},
    )
    result = dynamodb.get_item(TableName="moto-test", Key={"id": {"S": "1"}})
    assert result["Item"]["myNum"]["N"] == "3"


@mock_aws
def test_non_existing_attribute_should_raise_exception():
    """
    Does error message get correctly raised if attribute is referenced but it does not exist for the item.
    """
    dynamodb = create_simple_table_and_return_client()

    try:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = no_attr + MyStr",
        )
        assert False, "Validation exception not thrown"
    except dynamodb.exceptions.ClientError as e:
        assert_correct_client_error(
            e,
            "ValidationException",
            "The provided expression refers to an attribute that does not exist in the item",
        )


@mock_aws
def test_update_expression_with_plus_in_attribute_name():
    """
    Does error message get correctly raised if attribute contains a plus and is passed in without an AttributeName. And
    lhs & rhs are not attribute IDs by themselve.
    """
    dynamodb = create_simple_table_and_return_client()

    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "my+Num": {"S": "1"}, "MyStr": {"S": "aaa"}},
    )
    try:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = my+Num",
        )
        assert False, "Validation exception not thrown"
    except dynamodb.exceptions.ClientError as e:
        assert_correct_client_error(
            e,
            "ValidationException",
            "The provided expression refers to an attribute that does not exist in the item",
        )


@mock_aws
def test_update_expression_with_minus_in_attribute_name():
    """
    Does error message get correctly raised if attribute contains a minus and is passed in without an AttributeName. And
    lhs & rhs are not attribute IDs by themselve.
    """
    dynamodb = create_simple_table_and_return_client()

    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "my-Num": {"S": "1"}, "MyStr": {"S": "aaa"}},
    )
    try:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = my-Num",
        )
        assert False, "Validation exception not thrown"
    except dynamodb.exceptions.ClientError as e:
        assert_correct_client_error(
            e,
            "ValidationException",
            "The provided expression refers to an attribute that does not exist in the item",
        )


@mock_aws
def test_update_expression_with_space_in_attribute_name():
    """
    Does error message get correctly raised if attribute contains a space and is passed in without an AttributeName. And
    lhs & rhs are not attribute IDs by themselves.
    """
    dynamodb = create_simple_table_and_return_client()

    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "my Num": {"S": "1"}, "MyStr": {"S": "aaa"}},
    )

    with pytest.raises(ClientError) as exc:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = my Num",
        )
    err = exc.value.response["Error"]
    assert_raise_syntax_error(err, "Num", "my Num")


@mock_aws
def test_summing_up_2_strings_raises_exception():
    """
    Update set supports different DynamoDB types but some operations are not supported. For example summing up 2 strings
    raises an exception.  It results in ClientError with code ValidationException:
        Saying An operand in the update expression has an incorrect data type
    """
    dynamodb = create_simple_table_and_return_client()

    try:
        dynamodb.update_item(
            TableName="moto-test",
            Key={"id": {"S": "1"}},
            UpdateExpression="SET MyStr = MyStr + MyStr",
        )
        assert False, "Validation exception not thrown"
    except dynamodb.exceptions.ClientError as e:
        assert_correct_client_error(
            e,
            "ValidationException",
            "An operand in the update expression has an incorrect data type",
        )


# https://github.com/getmoto/moto/issues/2806
@mock_aws
def test_update_item_with_attribute_in_right_hand_side():
    """
    After tokenization and building expression make sure referenced attributes are replaced with their current value
    """
    dynamodb = create_simple_table_and_return_client()

    # Make sure there are 2 values
    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "myVal1": {"S": "Value1"}, "myVal2": {"S": "Value2"}},
    )

    dynamodb.update_item(
        TableName="moto-test",
        Key={"id": {"S": "1"}},
        UpdateExpression="SET myVal1 = myVal2",
    )

    result = dynamodb.get_item(TableName="moto-test", Key={"id": {"S": "1"}})
    assert result["Item"]["myVal1"]["S"] == result["Item"]["myVal2"]["S"] == "Value2"


@mock_aws
def test_multiple_updates():
    dynamodb = create_simple_table_and_return_client()
    dynamodb.put_item(
        TableName="moto-test",
        Item={"id": {"S": "1"}, "myNum": {"N": "1"}, "path": {"N": "6"}},
    )
    dynamodb.update_item(
        TableName="moto-test",
        Key={"id": {"S": "1"}},
        UpdateExpression="SET myNum = #p + :val, newAttr = myNum",
        ExpressionAttributeValues={":val": {"N": "1"}},
        ExpressionAttributeNames={"#p": "path"},
    )
    result = dynamodb.get_item(TableName="moto-test", Key={"id": {"S": "1"}})["Item"]
    expected_result = {
        "myNum": {"N": "7"},
        "newAttr": {"N": "1"},
        "path": {"N": "6"},
        "id": {"S": "1"},
    }
    assert result == expected_result


@mock_aws
def test_update_item_atomic_counter():
    table = "table_t"
    ddb_mock = boto3.client("dynamodb", region_name="eu-west-3")
    ddb_mock.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "t_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "t_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    key = {"t_id": {"S": "item1"}}

    ddb_mock.put_item(
        TableName=table,
        Item={"t_id": {"S": "item1"}, "n_i": {"N": "5"}, "n_f": {"N": "5.3"}},
    )

    ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="set n_i = n_i + :inc1, n_f = n_f + :inc2",
        ExpressionAttributeValues={":inc1": {"N": "1.2"}, ":inc2": {"N": "0.05"}},
    )
    updated_item = ddb_mock.get_item(TableName=table, Key=key)["Item"]
    assert updated_item["n_i"]["N"] == "6.2"
    assert updated_item["n_f"]["N"] == "5.35"


@mock_aws
def test_update_item_atomic_counter_return_values():
    table = "table_t"
    ddb_mock = boto3.client("dynamodb", region_name="eu-west-3")
    ddb_mock.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "t_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "t_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    key = {"t_id": {"S": "item1"}}

    ddb_mock.put_item(TableName=table, Item={"t_id": {"S": "item1"}, "v": {"N": "5"}})

    response = ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="set v = v + :inc",
        ExpressionAttributeValues={":inc": {"N": "1"}},
        ReturnValues="UPDATED_OLD",
    )
    # v has been updated, and should be returned here
    assert response["Attributes"]["v"]["N"] == "5"

    # second update
    response = ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="set v = v + :inc",
        ExpressionAttributeValues={":inc": {"N": "1"}},
        ReturnValues="UPDATED_OLD",
    )
    # v has been updated, and should be returned here
    assert response["Attributes"]["v"]["N"] == "6"

    # third update
    response = ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="set v = v + :inc",
        ExpressionAttributeValues={":inc": {"N": "1"}},
        ReturnValues="UPDATED_NEW",
    )
    # v has been updated, and should be returned here
    assert response["Attributes"]["v"]["N"] == "8"


@mock_aws
def test_update_item_atomic_counter_from_zero():
    table = "table_t"
    ddb_mock = boto3.client("dynamodb", region_name="eu-west-1")
    ddb_mock.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "t_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "t_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    key = {"t_id": {"S": "item1"}}

    ddb_mock.put_item(TableName=table, Item=key)

    ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="add n_i :inc1, n_f :inc2",
        ExpressionAttributeValues={":inc1": {"N": "1.2"}, ":inc2": {"N": "-0.5"}},
    )
    updated_item = ddb_mock.get_item(TableName=table, Key=key)["Item"]
    assert updated_item["n_i"]["N"] == "1.2"
    assert updated_item["n_f"]["N"] == "-0.5"


@mock_aws
def test_update_item_add_to_non_existent_set():
    table = "table_t"
    ddb_mock = boto3.client("dynamodb", region_name="eu-west-1")
    ddb_mock.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "t_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "t_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    key = {"t_id": {"S": "item1"}}
    ddb_mock.put_item(TableName=table, Item=key)

    ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="add s_i :s1",
        ExpressionAttributeValues={":s1": {"SS": ["hello"]}},
    )
    updated_item = ddb_mock.get_item(TableName=table, Key=key)["Item"]
    assert updated_item["s_i"]["SS"] == ["hello"]


@mock_aws
def test_update_item_add_to_non_existent_number_set():
    table = "table_t"
    ddb_mock = boto3.client("dynamodb", region_name="eu-west-1")
    ddb_mock.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "t_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "t_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    key = {"t_id": {"S": "item1"}}
    ddb_mock.put_item(TableName=table, Item=key)

    ddb_mock.update_item(
        TableName=table,
        Key=key,
        UpdateExpression="add s_i :s1",
        ExpressionAttributeValues={":s1": {"NS": ["3"]}},
    )
    updated_item = ddb_mock.get_item(TableName=table, Key=key)["Item"]
    assert updated_item["s_i"]["NS"] == ["3"]


@pytest.mark.aws_verified
@dynamodb_aws_verified(add_gsi_range=True, gsi_projection_type="KEYS_ONLY")
def test_gsi_projection_type_keys_only(table_name=None):
    item = {
        "pk": "pk-1",
        "gsi_pk": "gsi-pk",
        "gsi_sk": "gsi-sk",
        "someAttribute": "lore ipsum",
    }

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    table = dynamodb.Table(table_name)
    table.put_item(Item=item)

    items = table.query(
        KeyConditionExpression=Key("gsi_pk").eq("gsi-pk"), IndexName="test_gsi"
    )["Items"]
    assert len(items) == 1
    # Item should only include GSI Keys and Table Keys, as per the ProjectionType
    assert items[0] == {
        "gsi_pk": "gsi-pk",
        "gsi_sk": "gsi-sk",
        "pk": "pk-1",
    }


@mock_aws
def test_gsi_projection_type_include():
    table_schema = {
        "KeySchema": [{"AttributeName": "partitionKey", "KeyType": "HASH"}],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "GSI-INC",
                "KeySchema": [
                    {"AttributeName": "gsiK1PartitionKey", "KeyType": "HASH"},
                    {"AttributeName": "gsiK1SortKey", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": ["projectedAttribute"],
                },
            }
        ],
        "AttributeDefinitions": [
            {"AttributeName": "partitionKey", "AttributeType": "S"},
            {"AttributeName": "gsiK1PartitionKey", "AttributeType": "S"},
            {"AttributeName": "gsiK1SortKey", "AttributeType": "S"},
        ],
    }

    item = {
        "partitionKey": "pk-1",
        "gsiK1PartitionKey": "gsi-pk",
        "gsiK1SortKey": "gsi-sk",
        "projectedAttribute": "lore ipsum",
        "nonProjectedAttribute": "dolor sit amet",
    }

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="test-table", BillingMode="PAY_PER_REQUEST", **table_schema
    )
    table = dynamodb.Table("test-table")
    table.put_item(Item=item)

    items = table.query(
        KeyConditionExpression=Key("gsiK1PartitionKey").eq("gsi-pk"),
        IndexName="GSI-INC",
    )["Items"]
    assert len(items) == 1
    # Item should only include keys and additionally projected attributes only
    assert items[0] == {
        "gsiK1PartitionKey": "gsi-pk",
        "gsiK1SortKey": "gsi-sk",
        "partitionKey": "pk-1",
        "projectedAttribute": "lore ipsum",
    }

    # Same when scanning the table
    items = table.scan(IndexName="GSI-INC")["Items"]
    assert items[0] == {
        "gsiK1PartitionKey": "gsi-pk",
        "gsiK1SortKey": "gsi-sk",
        "partitionKey": "pk-1",
        "projectedAttribute": "lore ipsum",
    }


@pytest.mark.aws_verified
@dynamodb_aws_verified(add_range=True, add_lsi=True, lsi_projection_type="KEYS_ONLY")
def test_lsi_projection_type_keys_only(table_name=None):
    item = {
        "pk": "pk-1",
        "sk": "sk-1",
        "lsi_sk": "lsi-sk",
        "someAttribute": "lore ipsum",
    }

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(table_name)
    table.put_item(Item=item)

    items = table.query(
        KeyConditionExpression=Key("pk").eq("pk-1"), IndexName="test_lsi"
    )["Items"]
    # Item should only include GSI Keys and Table Keys, as per the ProjectionType
    assert items == [{"pk": "pk-1", "sk": "sk-1", "lsi_sk": "lsi-sk"}]

    # Same when scanning the table
    items = table.scan(IndexName="test_lsi")["Items"]
    assert items[0] == {
        "lsi_sk": "lsi-sk",
        "pk": "pk-1",
        "sk": "sk-1",
    }


@pytest.mark.aws_verified
@dynamodb_aws_verified()
def test_set_attribute_is_dropped_if_empty_after_update_expression(table_name=None):
    set_item = "test-data"
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.update_item(
        TableName=table_name,
        Key={"pk": {"S": "item1"}},
        UpdateExpression="ADD orders :order",
        ExpressionAttributeValues={":order": {"SS": [set_item]}},
    )
    items = client.scan(TableName=table_name, ProjectionExpression="pk, orders")[
        "Items"
    ]
    assert items == [{"pk": {"S": "item1"}, "orders": {"SS": ["test-data"]}}]

    client.update_item(
        TableName=table_name,
        Key={"pk": {"S": "item1"}},
        UpdateExpression="DELETE orders :order",
        ExpressionAttributeValues={":order": {"SS": [set_item]}},
    )
    items = client.scan(TableName=table_name, ProjectionExpression="pk, orders")[
        "Items"
    ]
    assert items == [{"pk": {"S": "item1"}}]


@mock_aws
def test_dynamodb_update_item_fails_on_string_sets():
    dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
    client = boto3.client("dynamodb", region_name="eu-west-1")

    table = dynamodb.create_table(
        TableName="test",
        KeySchema=[{"AttributeName": "record_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "record_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.meta.client.get_waiter("table_exists").wait(TableName="test")
    attribute = {"test_field": {"Value": {"SS": ["test1", "test2"]}, "Action": "PUT"}}

    client.update_item(
        TableName="test",
        Key={"record_id": {"S": "testrecord"}},
        AttributeUpdates=attribute,
    )


@mock_aws
def test_update_item_add_to_list_using_legacy_attribute_updates():
    resource = boto3.resource("dynamodb", region_name="us-west-2")
    resource.create_table(
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = resource.Table("TestTable")
    table.wait_until_exists()
    table.put_item(Item={"id": "list_add", "attr": ["a", "b", "c"]})

    table.update_item(
        TableName="TestTable",
        Key={"id": "list_add"},
        AttributeUpdates={"attr": {"Action": "ADD", "Value": ["d", "e"]}},
    )

    resp = table.get_item(Key={"id": "list_add"})
    assert resp["Item"]["attr"] == ["a", "b", "c", "d", "e"]


@mock_aws
def test_update_item_add_to_num_set_using_legacy_attribute_updates():
    resource = boto3.resource("dynamodb", region_name="us-west-2")
    resource.create_table(
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        TableName="TestTable",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = resource.Table("TestTable")
    table.wait_until_exists()
    table.put_item(Item={"id": "set_add", "attr": {1, 2}})

    table.update_item(
        TableName="TestTable",
        Key={"id": "set_add"},
        AttributeUpdates={"attr": {"Action": "PUT", "Value": {1, 2, 3}}},
    )

    table.update_item(
        TableName="TestTable",
        Key={"id": "set_add"},
        AttributeUpdates={"attr": {"Action": "ADD", "Value": {4, 5}}},
    )

    resp = table.get_item(Key={"id": "set_add"})
    assert resp["Item"]["attr"] == {1, 2, 3, 4, 5}

    table.update_item(
        TableName="TestTable",
        Key={"id": "set_add"},
        AttributeUpdates={"attr": {"Action": "DELETE", "Value": {2, 3}}},
    )

    resp = table.get_item(Key={"id": "set_add"})
    assert resp["Item"]["attr"] == {1, 4, 5}


@mock_aws
def test_get_item_for_non_existent_table_raises_error():
    client = boto3.client("dynamodb", "us-east-1")
    with pytest.raises(ClientError) as ex:
        client.get_item(TableName="non-existent", Key={"site-id": {"S": "foo"}})
    assert ex.value.response["Error"]["Code"] == "ResourceNotFoundException"
    assert ex.value.response["Error"]["Message"] == "Requested resource not found"


@mock_aws
def test_error_when_providing_expression_and_nonexpression_params():
    client = boto3.client("dynamodb", "eu-central-1")
    table_name = "testtable"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "pkey", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pkey", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    with pytest.raises(ClientError) as ex:
        client.update_item(
            TableName=table_name,
            Key={"pkey": {"S": "testrecord"}},
            AttributeUpdates={
                "test_field": {"Value": {"SS": ["test1", "test2"]}, "Action": "PUT"}
            },
            UpdateExpression="DELETE orders :order",
            ExpressionAttributeValues={":order": {"SS": ["item"]}},
        )
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert (
        err["Message"]
        == "Can not use both expression and non-expression parameters in the same request: Non-expression parameters: {AttributeUpdates} Expression parameters: {UpdateExpression}"
    )


@mock_aws
def test_error_when_providing_empty_update_expression():
    client = boto3.client("dynamodb", "eu-central-1")
    table_name = "testtable"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "pkey", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pkey", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    with pytest.raises(ClientError) as ex:
        client.update_item(
            TableName=table_name,
            Key={"pkey": {"S": "testrecord"}},
            UpdateExpression="",
            ExpressionAttributeValues={":order": {"SS": ["item"]}},
        )
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert (
        err["Message"] == "Invalid UpdateExpression: The expression can not be empty;"
    )


@mock_aws
def test_attribute_item_delete():
    name = "TestTable"
    conn = boto3.client("dynamodb", region_name="eu-west-1")
    conn.create_table(
        TableName=name,
        AttributeDefinitions=[{"AttributeName": "name", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "name", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )

    item_name = "foo"
    conn.put_item(
        TableName=name, Item={"name": {"S": item_name}, "extra": {"S": "bar"}}
    )

    conn.update_item(
        TableName=name,
        Key={"name": {"S": item_name}},
        AttributeUpdates={"extra": {"Action": "DELETE"}},
    )
    items = conn.scan(TableName=name)["Items"]
    assert items == [{"name": {"S": "foo"}}]


@mock_aws
def test_gsi_key_can_be_updated():
    name = "TestTable"
    conn = boto3.client("dynamodb", region_name="eu-west-2")
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "main_key", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "main_key", "AttributeType": "S"},
            {"AttributeName": "index_key", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_index",
                "KeySchema": [{"AttributeName": "index_key", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
    )

    conn.put_item(
        TableName=name,
        Item={
            "main_key": {"S": "testkey1"},
            "extra_data": {"S": "testdata"},
            "index_key": {"S": "indexkey1"},
        },
    )

    conn.update_item(
        TableName=name,
        Key={"main_key": {"S": "testkey1"}},
        UpdateExpression="set index_key=:new_index_key",
        ExpressionAttributeValues={":new_index_key": {"S": "new_value"}},
    )

    item = conn.scan(TableName=name)["Items"][0]
    assert item["index_key"] == {"S": "new_value"}
    assert item["main_key"] == {"S": "testkey1"}


@mock_aws
def test_gsi_key_cannot_be_empty():
    name = "TestTable"
    conn = boto3.client("dynamodb", region_name="eu-west-2")
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "main_key", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "main_key", "AttributeType": "S"},
            {"AttributeName": "index_key", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_index",
                "KeySchema": [{"AttributeName": "index_key", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
    )

    conn.put_item(
        TableName=name,
        Item={
            "main_key": {"S": "testkey1"},
            "extra_data": {"S": "testdata"},
            "index_key": {"S": "indexkey1"},
        },
    )

    with pytest.raises(ClientError) as ex:
        conn.update_item(
            TableName=name,
            Key={"main_key": {"S": "testkey1"}},
            UpdateExpression="set index_key=:new_index_key",
            ExpressionAttributeValues={":new_index_key": {"S": ""}},
        )
    err = ex.value.response["Error"]
    assert err["Code"] == "ValidationException"
    assert (
        err["Message"]
        == "One or more parameter values are not valid. The update expression attempted to update a secondary index key to a value that is not supported. The AttributeValue for a key attribute cannot contain an empty string value."
    )


@mock_aws
def test_create_backup_for_non_existent_table_raises_error():
    client = boto3.client("dynamodb", "us-east-1")
    with pytest.raises(ClientError) as ex:
        client.create_backup(TableName="non-existent", BackupName="backup")
    error = ex.value.response["Error"]
    assert error["Code"] == "TableNotFoundException"
    assert error["Message"] == "Table not found: non-existent"


@mock_aws
def test_create_backup():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    backup_name = "backup-test-table"
    resp = client.create_backup(TableName=table_name, BackupName=backup_name)
    details = resp.get("BackupDetails")
    assert table_name in details["BackupArn"]
    assert details["BackupName"] == backup_name
    assert isinstance(details["BackupSizeBytes"], int)
    assert "BackupStatus" in details
    assert details["BackupType"] == "USER"
    assert isinstance(details["BackupCreationDateTime"], datetime)


@mock_aws
def test_create_backup_using_arn():
    client = boto3.client("dynamodb", "us-east-1")
    table_arn = client.create_table(
        TableName="test-table",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )["TableDescription"]["TableArn"]
    client.create_backup(TableName=table_arn, BackupName="n/a")

    backups = client.list_backups(TableName=table_arn)["BackupSummaries"]
    assert len(backups) == 1


@mock_aws
def test_create_multiple_backups_with_same_name():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    backup_name = "backup-test-table"
    backup_arns = []
    for _ in range(4):
        backup = client.create_backup(TableName=table_name, BackupName=backup_name).get(
            "BackupDetails"
        )
        assert backup["BackupName"] == backup_name
        assert backup["BackupArn"] not in backup_arns
        backup_arns.append(backup["BackupArn"])


@mock_aws
def test_describe_backup_for_non_existent_backup_raises_error():
    client = boto3.client("dynamodb", "us-east-1")
    non_existent_arn = "arn:aws:dynamodb:us-east-1:123456789012:table/table-name/backup/01623095754481-2cfcd6f9"
    with pytest.raises(ClientError) as ex:
        client.describe_backup(BackupArn=non_existent_arn)
    error = ex.value.response["Error"]
    assert error["Code"] == "BackupNotFoundException"
    assert error["Message"] == f"Backup not found: {non_existent_arn}"


@mock_aws
def test_describe_backup():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    table = client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    ).get("TableDescription")
    backup_name = "backup-test-table"
    backup_arn = (
        client.create_backup(TableName=table_name, BackupName=backup_name)
        .get("BackupDetails")
        .get("BackupArn")
    )
    resp = client.describe_backup(BackupArn=backup_arn)
    description = resp.get("BackupDescription")
    details = description.get("BackupDetails")
    assert table_name in details["BackupArn"]
    assert details["BackupName"] == backup_name
    assert isinstance(details["BackupSizeBytes"], int)
    assert "BackupStatus" in details
    assert details["BackupType"] == "USER"
    assert isinstance(details["BackupCreationDateTime"], datetime)
    source = description.get("SourceTableDetails")
    assert source["TableName"] == table_name
    assert source["TableArn"] == table["TableArn"]
    assert isinstance(source["TableSizeBytes"], int)
    assert source["KeySchema"] == table["KeySchema"]
    assert source["TableCreationDateTime"] == table["CreationDateTime"]
    assert isinstance(source["ProvisionedThroughput"], dict)
    assert source["ItemCount"] == table["ItemCount"]


@mock_aws
def test_list_backups_for_non_existent_table():
    client = boto3.client("dynamodb", "us-east-1")
    resp = client.list_backups(TableName="non-existent")
    assert len(resp["BackupSummaries"]) == 0


@mock_aws
def test_list_backups():
    client = boto3.client("dynamodb", "us-east-1")
    table_names = ["test-table-1", "test-table-2"]
    backup_names = ["backup-1", "backup-2"]
    for table_name in table_names:
        client.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        for backup_name in backup_names:
            client.create_backup(TableName=table_name, BackupName=backup_name)
    resp = client.list_backups(BackupType="USER")
    assert len(resp["BackupSummaries"]) == 4
    for table_name in table_names:
        resp = client.list_backups(TableName=table_name)
        assert len(resp["BackupSummaries"]) == 2
        for summary in resp["BackupSummaries"]:
            assert summary["TableName"] == table_name
            assert table_name in summary["TableArn"]
            assert summary["BackupName"] in backup_names
            assert "BackupArn" in summary
            assert isinstance(summary["BackupCreationDateTime"], datetime)
            assert "BackupStatus" in summary
            assert summary["BackupType"] in ["USER", "SYSTEM"]
            assert isinstance(summary["BackupSizeBytes"], int)


@mock_aws
def test_restore_table_from_non_existent_backup_raises_error():
    client = boto3.client("dynamodb", "us-east-1")
    non_existent_arn = "arn:aws:dynamodb:us-east-1:123456789012:table/table-name/backup/01623095754481-2cfcd6f9"
    with pytest.raises(ClientError) as ex:
        client.restore_table_from_backup(
            TargetTableName="from-backup", BackupArn=non_existent_arn
        )
    error = ex.value.response["Error"]
    assert error["Code"] == "BackupNotFoundException"
    assert error["Message"] == f"Backup not found: {non_existent_arn}"


@mock_aws
def test_restore_table_from_backup_raises_error_when_table_already_exists():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    resp = client.create_backup(TableName=table_name, BackupName="backup")
    backup = resp.get("BackupDetails")
    with pytest.raises(ClientError) as ex:
        client.restore_table_from_backup(
            TargetTableName=table_name, BackupArn=backup["BackupArn"]
        )
    error = ex.value.response["Error"]
    assert error["Code"] == "TableAlreadyExistsException"
    assert error["Message"] == f"Table already exists: {table_name}"


@mock_aws
def test_restore_table_from_backup():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    resp = client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = resp.get("TableDescription")
    for i in range(5):
        client.put_item(TableName=table_name, Item={"id": {"S": f"item {i}"}})

    backup_arn = (
        client.create_backup(TableName=table_name, BackupName="backup")
        .get("BackupDetails")
        .get("BackupArn")
    )

    restored_table_name = "restored-from-backup"
    restored = client.restore_table_from_backup(
        TargetTableName=restored_table_name, BackupArn=backup_arn
    ).get("TableDescription")
    assert restored["AttributeDefinitions"] == table["AttributeDefinitions"]
    assert restored["TableName"] == restored_table_name
    assert restored["KeySchema"] == table["KeySchema"]
    assert "TableStatus" in restored
    assert restored["ItemCount"] == 5
    assert restored_table_name in restored["TableArn"]
    assert isinstance(restored["RestoreSummary"], dict)
    summary = restored.get("RestoreSummary")
    assert summary["SourceBackupArn"] == backup_arn
    assert summary["SourceTableArn"] == table["TableArn"]
    assert isinstance(summary["RestoreDateTime"], datetime)
    assert summary["RestoreInProgress"] is False


@mock_aws
def test_restore_table_to_point_in_time():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    resp = client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    table = resp.get("TableDescription")
    for i in range(5):
        client.put_item(TableName=table_name, Item={"id": {"S": f"item {i}"}})

    restored_table_name = "restored-from-pit"
    restored = client.restore_table_to_point_in_time(
        TargetTableName=restored_table_name, SourceTableName=table_name
    ).get("TableDescription")
    assert restored["TableName"] == restored_table_name
    assert restored["KeySchema"] == table["KeySchema"]
    assert "TableStatus" in restored
    assert restored["ItemCount"] == 5
    assert restored_table_name in restored["TableArn"]
    assert isinstance(restored["RestoreSummary"], dict)
    summary = restored.get("RestoreSummary")
    assert summary["SourceTableArn"] == table["TableArn"]
    assert isinstance(summary["RestoreDateTime"], datetime)
    assert summary["RestoreInProgress"] is False


@mock_aws
def test_restore_table_to_point_in_time_raises_error_when_source_not_exist():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    restored_table_name = "restored-from-pit"
    with pytest.raises(ClientError) as ex:
        client.restore_table_to_point_in_time(
            TargetTableName=restored_table_name, SourceTableName=table_name
        )
    error = ex.value.response["Error"]
    assert error["Code"] == "SourceTableNotFoundException"
    assert error["Message"] == f"Source table not found: {table_name}"


@mock_aws
def test_restore_table_to_point_in_time_raises_error_when_dest_exist():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table"
    restored_table_name = "restored-from-pit"
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    client.create_table(
        TableName=restored_table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    with pytest.raises(ClientError) as ex:
        client.restore_table_to_point_in_time(
            TargetTableName=restored_table_name, SourceTableName=table_name
        )
    error = ex.value.response["Error"]
    assert error["Code"] == "TableAlreadyExistsException"
    assert error["Message"] == f"Table already exists: {restored_table_name}"


@mock_aws
def test_delete_non_existent_backup_raises_error():
    client = boto3.client("dynamodb", "us-east-1")
    non_existent_arn = "arn:aws:dynamodb:us-east-1:123456789012:table/table-name/backup/01623095754481-2cfcd6f9"
    with pytest.raises(ClientError) as ex:
        client.delete_backup(BackupArn=non_existent_arn)
    error = ex.value.response["Error"]
    assert error["Code"] == "BackupNotFoundException"
    assert error["Message"] == f"Backup not found: {non_existent_arn}"


@mock_aws
def test_delete_backup():
    client = boto3.client("dynamodb", "us-east-1")
    table_name = "test-table-1"
    backup_names = ["backup-1", "backup-2"]
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    for backup_name in backup_names:
        client.create_backup(TableName=table_name, BackupName=backup_name)
    resp = client.list_backups(TableName=table_name, BackupType="USER")
    assert len(resp["BackupSummaries"]) == 2
    backup_to_delete = resp["BackupSummaries"][0]["BackupArn"]
    backup_deleted = client.delete_backup(BackupArn=backup_to_delete).get(
        "BackupDescription"
    )
    assert "SourceTableDetails" in backup_deleted
    assert "BackupDetails" in backup_deleted
    details = backup_deleted["BackupDetails"]
    assert details["BackupArn"] == backup_to_delete
    assert details["BackupName"] in backup_names
    assert details["BackupStatus"] == "DELETED"
    resp = client.list_backups(TableName=table_name, BackupType="USER")
    assert len(resp["BackupSummaries"]) == 1


@mock_aws
def test_source_and_restored_table_items_are_not_linked():
    client = boto3.client("dynamodb", "us-east-1")

    def add_guids_to_table(table, num_items):
        guids = []
        for _ in range(num_items):
            guid = str(uuid.uuid4())
            client.put_item(TableName=table, Item={"id": {"S": guid}})
            guids.append(guid)
        return guids

    source_table_name = "source-table"
    client.create_table(
        TableName=source_table_name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    guids_original = add_guids_to_table(source_table_name, 5)

    backup_arn = (
        client.create_backup(TableName=source_table_name, BackupName="backup")
        .get("BackupDetails")
        .get("BackupArn")
    )
    guids_added_after_backup = add_guids_to_table(source_table_name, 5)

    restored_table_name = "restored-from-backup"
    client.restore_table_from_backup(
        TargetTableName=restored_table_name, BackupArn=backup_arn
    )
    guids_added_after_restore = add_guids_to_table(restored_table_name, 5)

    source_table_items = client.scan(TableName=source_table_name)
    assert source_table_items["Count"] == 10
    source_table_guids = [x["id"]["S"] for x in source_table_items["Items"]]
    assert set(source_table_guids) == set(guids_original) | set(
        guids_added_after_backup
    )

    restored_table_items = client.scan(TableName=restored_table_name)
    assert restored_table_items["Count"] == 10
    restored_table_guids = [x["id"]["S"] for x in restored_table_items["Items"]]
    assert set(restored_table_guids) == set(guids_original) | set(
        guids_added_after_restore
    )


@mock_aws
@pytest.mark.parametrize("region", ["eu-central-1", "ap-south-1"])
def test_describe_endpoints(region):
    client = boto3.client("dynamodb", region)
    res = client.describe_endpoints()["Endpoints"]
    assert res == [
        {
            "Address": f"dynamodb.{region}.amazonaws.com",
            "CachePeriodInMinutes": 1440,
        },
    ]


@mock_aws
def test_update_non_existing_item_raises_error_and_does_not_contain_item_afterwards():
    """
    https://github.com/getmoto/moto/issues/3729
    Exception is raised, but item was persisted anyway
    Happened because we would create a placeholder, before validating/executing the UpdateExpression
    :return:
    """
    name = "TestTable"
    conn = boto3.client("dynamodb", region_name="us-west-2")
    hkey = "primary_partition_key"
    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": hkey, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": hkey, "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )
    update_expression = {
        "Key": {hkey: "some_identification_string"},
        "UpdateExpression": "set #AA.#AB = :aa",
        "ExpressionAttributeValues": {":aa": "abc"},
        "ExpressionAttributeNames": {"#AA": "some_dict", "#AB": "key1"},
        "ConditionExpression": "attribute_not_exists(#AA.#AB)",
    }
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(name)
    with pytest.raises(ClientError) as err:
        table.update_item(**update_expression)
    assert err.value.response["Error"]["Code"] == "ValidationException"

    assert len(conn.scan(TableName=name)["Items"]) == 0


@mock_aws
def test_gsi_lastevaluatedkey():
    # github.com/getmoto/moto/issues/3968
    conn = boto3.resource("dynamodb", region_name="us-west-2")
    name = "test-table"
    table = conn.Table(name)

    conn.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "main_key", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "main_key", "AttributeType": "S"},
            {"AttributeName": "index_key", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_index",
                "KeySchema": [{"AttributeName": "index_key", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
    )

    table.put_item(
        Item={
            "main_key": "testkey1",
            "extra_data": "testdata",
            "index_key": "indexkey",
        }
    )
    table.put_item(
        Item={
            "main_key": "testkey2",
            "extra_data": "testdata",
            "index_key": "indexkey",
        }
    )

    response = table.query(
        Limit=1,
        KeyConditionExpression=Key("index_key").eq("indexkey"),
        IndexName="test_index",
    )

    items = response["Items"]
    assert len(items) == 1
    assert items[0] == {
        "main_key": "testkey1",
        "extra_data": "testdata",
        "index_key": "indexkey",
    }

    last_evaluated_key = response["LastEvaluatedKey"]
    assert len(last_evaluated_key) == 2
    assert last_evaluated_key == {"main_key": "testkey1", "index_key": "indexkey"}


@mock_aws
def test_filter_expression_execution_order():
    # As mentioned here: https://github.com/getmoto/moto/issues/3909
    # and documented here: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.html#Query.FilterExpression
    # the filter expression should be evaluated after the query.
    # The same applies to scan operations:
    # https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Scan.html#Scan.FilterExpression

    # If we set limit=1 and apply a filter expression whixh excludes the first result
    # then we should get no items in response.

    conn = boto3.resource("dynamodb", region_name="us-west-2")
    name = "test-filter-expression-table"
    table = conn.Table(name)

    conn.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "hash_key", "KeyType": "HASH"},
            {"AttributeName": "range_key", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "hash_key", "AttributeType": "S"},
            {"AttributeName": "range_key", "AttributeType": "S"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    table.put_item(
        Item={"hash_key": "keyvalue", "range_key": "A", "filtered_attribute": "Y"}
    )
    table.put_item(
        Item={"hash_key": "keyvalue", "range_key": "B", "filtered_attribute": "Z"}
    )

    # test query

    query_response_1 = table.query(
        Limit=1,
        KeyConditionExpression=Key("hash_key").eq("keyvalue"),
        FilterExpression=Attr("filtered_attribute").eq("Z"),
    )

    query_items_1 = query_response_1["Items"]
    assert len(query_items_1) == 0

    query_last_evaluated_key = query_response_1["LastEvaluatedKey"]
    assert len(query_last_evaluated_key) == 2
    assert query_last_evaluated_key == {"hash_key": "keyvalue", "range_key": "A"}

    query_response_2 = table.query(
        Limit=1,
        KeyConditionExpression=Key("hash_key").eq("keyvalue"),
        FilterExpression=Attr("filtered_attribute").eq("Z"),
        ExclusiveStartKey=query_last_evaluated_key,
    )

    query_items_2 = query_response_2["Items"]
    assert len(query_items_2) == 1
    assert query_items_2[0] == {
        "hash_key": "keyvalue",
        "filtered_attribute": "Z",
        "range_key": "B",
    }

    # test scan

    scan_response_1 = table.scan(
        Limit=1, FilterExpression=Attr("filtered_attribute").eq("Z")
    )

    scan_items_1 = scan_response_1["Items"]
    assert len(scan_items_1) == 0

    scan_last_evaluated_key = scan_response_1["LastEvaluatedKey"]
    assert len(scan_last_evaluated_key) == 2
    assert scan_last_evaluated_key == {"hash_key": "keyvalue", "range_key": "A"}

    scan_response_2 = table.scan(
        Limit=1,
        FilterExpression=Attr("filtered_attribute").eq("Z"),
        ExclusiveStartKey=query_last_evaluated_key,
    )

    scan_items_2 = scan_response_2["Items"]
    assert scan_items_2 == [
        {"hash_key": "keyvalue", "filtered_attribute": "Z", "range_key": "B"}
    ]


@mock_aws
def test_projection_expression_execution_order():
    # projection expression needs to be applied after calculation of
    # LastEvaluatedKey as it is possible for LastEvaluatedKey to
    # include attributes which are not projected.

    conn = boto3.resource("dynamodb", region_name="us-west-2")
    name = "test-projection-expression-with-gsi"
    table = conn.Table(name)

    conn.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "hash_key", "KeyType": "HASH"},
            {"AttributeName": "range_key", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "hash_key", "AttributeType": "S"},
            {"AttributeName": "range_key", "AttributeType": "S"},
            {"AttributeName": "index_key", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_index",
                "KeySchema": [{"AttributeName": "index_key", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            }
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    table.put_item(Item={"hash_key": "keyvalue", "range_key": "A", "index_key": "Z"})
    table.put_item(Item={"hash_key": "keyvalue", "range_key": "B", "index_key": "Z"})

    # test query

    # if projection expression is applied before LastEvaluatedKey is computed
    # then this raises an exception.
    table.query(
        Limit=1,
        IndexName="test_index",
        KeyConditionExpression=Key("index_key").eq("Z"),
        ProjectionExpression="#a",
        ExpressionAttributeNames={"#a": "hashKey"},
    )
    # if projection expression is applied before LastEvaluatedKey is computed
    # then this raises an exception.
    table.scan(
        Limit=1,
        IndexName="test_index",
        ProjectionExpression="#a",
        ExpressionAttributeNames={"#a": "hashKey"},
    )


@mock_aws
def test_projection_expression_with_binary_attr():
    dynamo_resource = boto3.resource("dynamodb", region_name="us-east-1")
    dynamo_resource.create_table(
        TableName="test",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table = dynamo_resource.Table("test")
    table.put_item(Item={"pk": "pk", "sk": "sk", "key": b"value\xbf"})

    item = table.get_item(
        Key={"pk": "pk", "sk": "sk"},
        ExpressionAttributeNames={"#key": "key"},
        ProjectionExpression="#key",
    )["Item"]
    assert item == {"key": Binary(b"value\xbf")}

    item = table.scan()["Items"][0]
    assert item["key"] == Binary(b"value\xbf")

    item = table.query(KeyConditionExpression=Key("pk").eq("pk"))["Items"][0]
    assert item["key"] == Binary(b"value\xbf")


@mock_aws
def test_invalid_projection_expressions():
    table_name = "test-projection-expressions-table"
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "customer", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "customer", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    with pytest.raises(
        ClientError,
        match="ProjectionExpression: Attribute name is a reserved keyword; reserved keyword: name",
    ):
        client.scan(TableName=table_name, ProjectionExpression="name")
    with pytest.raises(
        ClientError, match="ProjectionExpression: Attribute name starts with a number"
    ):
        client.scan(TableName=table_name, ProjectionExpression="3ame")
    with pytest.raises(
        ClientError, match="ProjectionExpression: Attribute name contains white space"
    ):
        client.scan(TableName=table_name, ProjectionExpression="na me")

    with pytest.raises(
        ClientError,
        match="ProjectionExpression: Attribute name is a reserved keyword; reserved keyword: name",
    ):
        client.get_item(
            TableName=table_name,
            Key={"customer": {"S": "a"}},
            ProjectionExpression="name",
        )

    with pytest.raises(
        ClientError,
        match="ProjectionExpression: Attribute name is a reserved keyword; reserved keyword: name",
    ):
        client.query(
            TableName=table_name,
            KeyConditionExpression="a",
            ProjectionExpression="name",
        )

    with pytest.raises(
        ClientError,
        match="ProjectionExpression: Attribute name is a reserved keyword; reserved keyword: name",
    ):
        client.scan(TableName=table_name, ProjectionExpression="not_a_keyword, name")
    with pytest.raises(
        ClientError, match="ProjectionExpression: Attribute name starts with a number"
    ):
        client.scan(TableName=table_name, ProjectionExpression="not_a_keyword, 3ame")
    with pytest.raises(
        ClientError, match="ProjectionExpression: Attribute name contains white space"
    ):
        client.scan(TableName=table_name, ProjectionExpression="not_a_keyword, na me")


@mock_aws
def test_update_item_with_global_secondary_index():
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Create the DynamoDB table
    dynamodb.create_table(
        TableName="test",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "gsi_hash_key_s", "AttributeType": "S"},
            {"AttributeName": "gsi_hash_key_b", "AttributeType": "B"},
            {"AttributeName": "gsi_hash_key_n", "AttributeType": "N"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        GlobalSecondaryIndexes=[
            {
                "IndexName": "test_gsi_s",
                "KeySchema": [
                    {"AttributeName": "gsi_hash_key_s", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            },
            {
                "IndexName": "test_gsi_b",
                "KeySchema": [
                    {"AttributeName": "gsi_hash_key_b", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            },
            {
                "IndexName": "test_gsi_n",
                "KeySchema": [
                    {"AttributeName": "gsi_hash_key_n", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 1,
                    "WriteCapacityUnits": 1,
                },
            },
        ],
    )
    table = dynamodb.Table("test")

    table.put_item(
        Item={"id": "test1"},
    )

    for key_name, values in {
        "gsi_hash_key_s": [None, 0, b"binary"],
        "gsi_hash_key_b": [None, "", 0],
        "gsi_hash_key_n": [None, "", b"binary"],
    }.items():
        for v in values:
            with pytest.raises(ClientError) as ex:
                table.update_item(
                    Key={"id": "test1"},
                    UpdateExpression=f"SET {key_name} = :gsi_hash_key",
                    ExpressionAttributeValues={":gsi_hash_key": v},
                )
            err = ex.value.response["Error"]
            assert err["Code"] == "ValidationException"
            assert (
                "One or more parameter values were invalid: Type mismatch"
                in err["Message"]
            )


@pytest.mark.aws_verified
@dynamodb_aws_verified(add_range=True)
def test_query_with_unknown_last_evaluated_key(table_name=None):
    client = boto3.client("dynamodb", region_name="us-east-1")

    for i in range(10):
        client.put_item(
            TableName=table_name,
            Item={
                "pk": {"S": "hash_value"},
                "sk": {"S": f"range_value{i}"},
            },
        )

    p1 = client.query(
        TableName=table_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "pk"},
        ExpressionAttributeValues={":h": {"S": "hash_value"}},
        Limit=1,
    )
    assert p1["Items"] == [{"pk": {"S": "hash_value"}, "sk": {"S": "range_value0"}}]

    # Using the Exact ExclusiveStartKey provided
    p2 = client.query(
        TableName=table_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "pk"},
        ExpressionAttributeValues={":h": {"S": "hash_value"}},
        Limit=1,
        ExclusiveStartKey=p1["LastEvaluatedKey"],
    )
    assert p2["Items"] == [{"pk": {"S": "hash_value"}, "sk": {"S": "range_value1"}}]

    # We can change ExclusiveStartKey
    # It doesn't need to match - it just needs to be >= page1, but < page1
    different_key = copy.copy(p1["LastEvaluatedKey"])
    different_key["sk"]["S"] = different_key["sk"]["S"] + "0"
    p3 = client.query(
        TableName=table_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "pk"},
        ExpressionAttributeValues={":h": {"S": "hash_value"}},
        Limit=1,
        ExclusiveStartKey=different_key,
    )
    assert p3["Items"] == [{"pk": {"S": "hash_value"}, "sk": {"S": "range_value1"}}]

    # Sanity check - increasing the sk to something much greater will result in a different outcome
    different_key["sk"]["S"] = "range_value500"
    p4 = client.query(
        TableName=table_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "pk"},
        ExpressionAttributeValues={":h": {"S": "hash_value"}},
        Limit=1,
        ExclusiveStartKey=different_key,
    )
    assert p4["Items"] == [{"pk": {"S": "hash_value"}, "sk": {"S": "range_value6"}}]


@mock_aws
def test_query_with_gsi_reverse_paginated():
    client = boto3.client("dynamodb", region_name="us-west-2")
    table_name = "unit-test-table"
    index_name = "alternate"

    # Create table - GSI has dissimilar attributes from the main table
    client.create_table(
        AttributeDefinitions=[
            {"AttributeName": "pri", "AttributeType": "S"},
            {"AttributeName": "alt", "AttributeType": "S"},
        ],
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "pri", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": index_name,
                "KeySchema": [
                    {"AttributeName": "alt", "KeyType": "HASH"},
                    {"AttributeName": "pri", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Add some items. These are chosen so that the order of addition is not
    # lexical order for the chosen values, i.e.
    # pri: pri_5, pri_6, pri_7, pri_8, pri_9, pri_10, pri_11, pri_12, pri_13, pri_14
    # alt: alt_1, alt_1, alt_1, alt_2, alt_2,  alt_2,  alt_2,  alt_3,  alt_3,  alt_3
    for i in range(5, 15):
        client.put_item(
            TableName=table_name,
            Item={
                "pri": {"S": f"pri_{i}"},
                "alt": {"S": f"alt_{i // 4}"},
            },
        )

    # Let's reverse-sort a query on the alternate index. These items match "alt_2":
    # in insertion order: pri_8, pri_9, pri_10, pri_11
    # in lexical order: pri_10, pri_11, pri_8, pri_9
    # in reverse order: pri_9, pri_8, pri_11, pri_10
    p1 = client.query(
        TableName=table_name,
        IndexName=index_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "alt"},
        ExpressionAttributeValues={":h": {"S": "alt_2"}},
        ScanIndexForward=False,
        Limit=2,
    )
    assert p1["Items"] == [
        {"pri": {"S": "pri_9"}, "alt": {"S": "alt_2"}},
        {"pri": {"S": "pri_8"}, "alt": {"S": "alt_2"}},
    ]

    # Fetch the second page of results
    p2 = client.query(
        TableName=table_name,
        IndexName=index_name,
        KeyConditionExpression="#h = :h",
        ExpressionAttributeNames={"#h": "alt"},
        ExpressionAttributeValues={":h": {"S": "alt_2"}},
        ScanIndexForward=False,
        Limit=2,
        ExclusiveStartKey=p1["LastEvaluatedKey"],
    )
    assert p2["Items"] == [
        {"pri": {"S": "pri_11"}, "alt": {"S": "alt_2"}},
        {"pri": {"S": "pri_10"}, "alt": {"S": "alt_2"}},
    ]
    assert "LastEvaluatedKey" not in p2


@pytest.mark.aws_verified
@dynamodb_aws_verified()
def test_update_item_with_list_of_bytes(table_name=None):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(table_name)

    b1 = b"\n\x014\x18\xc3\xb0\xf8\xba\x06"
    b2 = b"\n\x012\x18\xc3\xb0\xf8\xba\x06"

    update = table.update_item(
        Key={"pk": "clientA"},
        UpdateExpression="SET #items = :new_items",
        ExpressionAttributeValues={":new_items": [b1, b2]},
        ExpressionAttributeNames={"#items": "items"},
        ReturnValues="UPDATED_NEW",
    )
    assert update["Attributes"]["items"] == [Binary(b1), Binary(b2)]

    get = table.get_item(Key={"pk": "clientA"})
    assert get["Item"] == {"pk": "clientA", "items": [Binary(b1), Binary(b2)]}
