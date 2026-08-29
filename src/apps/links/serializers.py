from rest_framework import serializers

from .models import Link, LinkGroup


class LinkGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = LinkGroup
        fields = ["id", "title", "cards_per_row"]


class LinkSerializer(serializers.ModelSerializer):
    author = serializers.PrimaryKeyRelatedField(read_only=True)
    favicon = serializers.ImageField(read_only=True)

    class Meta:
        model = Link
        fields = ["id", "group", "url", "title", "favicon", "author"]

    def validate_group(self, group):
        request = self.context["request"]
        if group.owner_id != request.user.id:
            raise serializers.ValidationError("Unknown group.")
        return group
