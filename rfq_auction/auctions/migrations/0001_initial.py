# Generated clean production migration - Consolidated schema

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuctionConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger_window_x', models.PositiveIntegerField(default=10, help_text='Trigger Window X: Minutes before close to monitor for bidding activity')),
                ('extension_duration_y', models.PositiveIntegerField(default=5, help_text='Extension Duration Y: Minutes to extend auction when triggered')),
                ('trigger_type', models.CharField(choices=[('BID_RECEIVED', 'Bid Received in Last X Minutes'), ('RANK_CHANGE', 'Any Supplier Rank Change in Last X Minutes'), ('L1_CHANGE', 'Lowest Bidder (L1) Rank Change')], default='BID_RECEIVED', help_text='Type of activity that triggers extension', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name_plural': 'Auction Configs',
            },
        ),
        migrations.CreateModel(
            name='Auction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='RFQ Name / Reference ID', max_length=255)),
                ('description', models.TextField(blank=True, help_text='RFQ Description')),
                ('bid_start_time', models.DateTimeField(help_text='Bid Start Date & Time')),
                ('bid_close_time', models.DateTimeField(help_text='Bid Close Date & Time')),
                ('forced_close_time', models.DateTimeField(help_text='Forced Bid Close Date & Time (must be > Bid Close Time)')),
                ('current_close_time', models.DateTimeField(blank=True, help_text='Current effective close time (with extensions)', null=True)),
                ('status', models.CharField(choices=[('ACTIVE', 'Active - Bidding Open'), ('CLOSED', 'Closed - Bidding Ended'), ('FORCE_CLOSED', 'Force Closed - Hard Deadline Reached')], default='ACTIVE', max_length=20)),
                ('total_extensions', models.PositiveIntegerField(default=0, help_text='Total number of times auction was extended')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('config', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auctions', to='auctions.auctionconfig')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='auctions_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Auctions',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Bid',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(decimal_places=2, help_text='Base price for quote', max_digits=12)),
                ('freight_charges', models.DecimalField(decimal_places=2, default=0, help_text='Freight charges', max_digits=10)),
                ('origin_charges', models.DecimalField(decimal_places=2, default=0, help_text='Origin/Pickup charges', max_digits=10)),
                ('destination_charges', models.DecimalField(decimal_places=2, default=0, help_text='Destination/Delivery charges', max_digits=10)),
                ('transit_time_days', models.PositiveIntegerField(help_text='Transit time in days')),
                ('quote_validity_days', models.PositiveIntegerField(help_text='Quote validity period in days')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bids', to='auctions.auction')),
                ('bidder', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bids', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Bids',
                'ordering': ['price'],
                'unique_together': {('auction', 'bidder')},
            },
        ),
        migrations.CreateModel(
            name='AuctionEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('BID_RECEIVED', 'Bid Received'), ('RANK_CHANGED', 'Rank Changed'), ('L1_CHANGED', 'L1 (Lowest Bidder) Changed'), ('EXTENDED', 'Auction Extended'), ('CLOSED', 'Auction Closed'), ('FORCE_CLOSED', 'Force Closed')], help_text='Type of event', max_length=20)),
                ('description', models.TextField(help_text='Detailed event description')),
                ('extension_reason', models.CharField(blank=True, help_text='Reason for extension trigger', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('auction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='auctions.auction')),
                ('bidder', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.SET_NULL, related_name='events', to=settings.AUTH_USER_MODEL, help_text='Bidder involved (if applicable)')),
            ],
            options={
                'verbose_name_plural': 'Auction Events',
                'ordering': ['-created_at'],
            },
        ),
    ]
