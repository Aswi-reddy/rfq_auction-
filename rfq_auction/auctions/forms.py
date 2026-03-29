from django import forms
from django.contrib.auth.models import User, Group
from auctions.models import Auction, Bid, AuctionConfig


# ========== BASE REGISTRATION FORM (DRY) ==========

class BaseRegisterForm(forms.Form):
    """
    ✨ Base registration form - Single source of truth.
    
    Eliminates 54 lines of duplicated code between
    AuctioneerRegisterForm and BidderRegisterForm.
    
    Use: Both forms inherit from this to avoid duplication.
    """
    username = forms.CharField(
        label='Username',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        label='Password',
        min_length=6
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'}),
        label='Confirm Password',
        min_length=6
    )
    
    def clean(self):
        """Validate password match and username uniqueness"""
        data = super().clean()
        pwd = data.get('password')
        pwd_confirm = data.get('password_confirm')
        username = data.get('username')
        
        if pwd and pwd_confirm and pwd != pwd_confirm:
            raise forms.ValidationError("Passwords don't match")
        
        if username and User.objects.filter(username=username).exists():
            raise forms.ValidationError("Username already taken")
        
        return data
    
    def save(self, group_name):
        """
        Save user with group assignment.
        
        Args:
            group_name (str): 'Auctioneer' or 'Bidder'
        
        Returns:
            User: Created Django user object
        """
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password']
        )
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user


# ========== AUCTIONEER FORMS ==========

class AuctioneerRegisterForm(BaseRegisterForm):
    """Auctioneer registration - inherits from BaseRegisterForm"""
    def save(self):
        return super().save(group_name='Auctioneer')


class AuctioneerLoginForm(forms.Form):
    """Auctioneer login"""
    username = forms.CharField(label='Username')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')


# ========== BIDDER FORMS ==========

class BidderRegisterForm(BaseRegisterForm):
    """Bidder registration - inherits from BaseRegisterForm"""
    def save(self):
        return super().save(group_name='Bidder')


class BidderLoginForm(forms.Form):
    """Bidder login"""
    username = forms.CharField(label='Username')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')


# ========== AUCTION FORMS ==========

class CreateAuctionForm(forms.ModelForm):
    """Create new auction (Auctioneer)"""
    
    # Explicitly declare datetime fields with BOTH widget AND input_formats.
    # Meta.widgets is IGNORED for fields declared explicitly on the form class.
    DATETIME_INPUT = forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M')
    DATETIME_FORMATS = ['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
    
    bid_start_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label='Bid Start Time'
    )
    bid_close_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label='Bid Close Time'
    )
    forced_close_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M'),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        label='Forced Close Time'
    )
    
    config_trigger_window_x = forms.IntegerField(
        label='Trigger Window X (minutes)', 
        initial=10, 
        min_value=5,
        max_value=60,
        help_text="Monitor for bidding in last X minutes before close (5-60 minutes)"
    )
    config_extension_duration_y = forms.IntegerField(
        label='Extension Duration Y (minutes)', 
        initial=5, 
        min_value=1,
        max_value=30,
        help_text="Extend auction by Y minutes when triggered (1-30 minutes)"
    )
    config_trigger_type = forms.ChoiceField(
        label='When to Trigger Extension',
        choices=AuctionConfig.TRIGGER_CHOICES,
        initial='BID_RECEIVED'
    )
    
    class Meta:
        model = Auction
        fields = ['name', 'description', 'bid_start_time', 'bid_close_time', 'forced_close_time']
        widgets = {
            'name': forms.TextInput(attrs={
                'type': 'text', 'placeholder': 'RFQ Name / Reference ID', 'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3, 'placeholder': 'RFQ Description', 'class': 'form-control'
            }),
            # NOTE: datetime widgets live on the explicit field declarations above.
            # Meta.widgets is IGNORED for explicitly declared fields.
        }
    
    def clean(self):
        """
        Comprehensive validation of auction configuration.
        
        Checks:
        ✓ Timing sequence (start < close < forced)
        ✓ Minimum bidding period (≥10 minutes)
        ✓ Minimum buffer between close and forced (≥5 minutes)
        ✓ Configuration bounds (X: 5-60, Y: 1-30)
        ✓ X fits within buffer
        """
        from datetime import timedelta
        
        data = super().clean()
        start = data.get('bid_start_time')
        close = data.get('bid_close_time')
        forced = data.get('forced_close_time')
        trigger_x = data.get('config_trigger_window_x')
        trigger_y = data.get('config_extension_duration_y')
        
        errors = {}
        
        # ── Validation 1: Timing Sequence ──
        if start and close:
            if start >= close:
                errors['bid_close_time'] = "Bid close time must be AFTER start time"
            else:
                # Minimum bidding period = 10 minutes
                min_bid_duration = timedelta(minutes=10)
                if (close - start) < min_bid_duration:
                    errors['bid_close_time'] = "Bidding period must be at least 10 minutes"
        
        if close and forced:
            if close >= forced:
                errors['forced_close_time'] = "Forced close time must be AFTER bid close time"
            else:
                # Minimum buffer for extensions = 5 minutes
                min_buffer = timedelta(minutes=5)
                gap = forced - close
                if gap < min_buffer:
                    gap_minutes = gap.total_seconds() / 60
                    errors['forced_close_time'] = (
                        f"Need at least 5 minutes buffer between close and forced close "
                        f"(currently {gap_minutes:.0f} minutes)"
                    )
        
        # ── Validation 2: Configuration Bounds ──
        # Note: min_value and max_value already validate these,
        # but we add explicit checks for better error messages
        if trigger_x and (trigger_x < 5 or trigger_x > 60):
            errors['config_trigger_window_x'] = "Trigger window must be between 5 and 60 minutes"
        
        if trigger_y and (trigger_y < 1 or trigger_y > 30):
            errors['config_extension_duration_y'] = "Extension duration must be between 1 and 30 minutes"
        
        # ── Validation 3: X vs Buffer Gap ──
        if trigger_x and close and forced:
            gap_minutes = (forced - close).total_seconds() / 60
            if trigger_x > gap_minutes:
                errors['config_trigger_window_x'] = (
                    f"Trigger window ({trigger_x} minutes) cannot exceed "
                    f"the buffer between close and forced ({gap_minutes:.0f} minutes). "
                    f"Reduce X or increase the buffer."
                )
        
        if errors:
            raise forms.ValidationError(errors)
        
        return data
    
    def save(self, commit=True, created_by=None):
        auction = super().save(commit=False)
        
        # Create config with X, Y, and trigger type
        config = AuctionConfig.objects.create(
            trigger_window_x=self.cleaned_data['config_trigger_window_x'],
            extension_duration_y=self.cleaned_data['config_extension_duration_y'],
            trigger_type=self.cleaned_data['config_trigger_type']
        )
        auction.config = config
        auction.created_by = created_by
        
        if commit:
            auction.save()
        
        return auction


# ========== BID FORMS ==========

class PlaceBidForm(forms.Form):
    """
    Place a bid on an auction (Bidder).
    
    This is a plain Form (not ModelForm) because:
    - Suppliers can place multiple bids (revisions)
    - We don't bind to an existing Bid instance
    - The AuctionEngine handles bid creation atomically
    """
    carrier_name = forms.CharField(
        max_length=255, required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Carrier Name', 'class': 'form-control'
        })
    )
    price = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={
            'step': '0.01', 'placeholder': 'Base Price (₹)', 'class': 'form-control'
        })
    )
    freight_charges = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={
            'step': '0.01', 'placeholder': 'Freight Charges (₹)', 'class': 'form-control'
        })
    )
    origin_charges = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={
            'step': '0.01', 'placeholder': 'Origin Charges (₹)', 'class': 'form-control'
        })
    )
    destination_charges = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={
            'step': '0.01', 'placeholder': 'Destination Charges (₹)', 'class': 'form-control'
        })
    )
    transit_time_days = forms.IntegerField(
        min_value=1, required=True,
        widget=forms.NumberInput(attrs={
            'placeholder': 'Transit Days', 'class': 'form-control'
        })
    )
    quote_validity_days = forms.IntegerField(
        min_value=1, initial=30, required=True,
        widget=forms.NumberInput(attrs={
            'placeholder': 'Validity Days', 'class': 'form-control'
        })
    )
