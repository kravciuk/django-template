from django import forms


class MultipleFileInput(forms.ClearableFileInput):
    """Django 5+'s FileInput natively supports allow_multiple_selected:
    renders the `multiple` HTML attribute and switches value_from_datadict
    to files.getlist(name) instead of files.get(name)."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that accepts several files at once - see Django's own
    "Uploading multiple files" recipe. clean() runs the normal per-file
    FileField.clean() (including any validators=[...] passed in) on each
    file individually, so callers get the usual per-file ValidationErrors.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return single_file_clean(data, initial) if data else []
