import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';

interface GroqApiKeyDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (apiKey: string) => Promise<void>;
}

export function GroqApiKeyDialog({ isOpen, onClose, onSave }: GroqApiKeyDialogProps) {
  const [apiKey, setApiKey] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setError('API key is required');
      return;
    }

    if (!apiKey.startsWith('gsk_')) {
      setError('Invalid Groq API key format (should start with gsk_)');
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      await onSave(apiKey);
      setApiKey(''); // Clear after save
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save API key');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Groq API Key Required</DialogTitle>
          <DialogDescription>
            To use real-time transcription, you need to provide your Groq API key.
            It will be stored securely in your personal settings.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col space-y-4 py-4">
          <div className="flex flex-col space-y-2">
            <Label htmlFor="apiKey">Groq API Key</Label>
            <Input
              id="apiKey"
              placeholder="gsk_..."
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (error) setError(null);
              }}
              disabled={isSaving}
              type="password"
              autoComplete="new-password"
            />
            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
          <p className="text-xs text-muted-foreground">
            You can get a free API key from the <a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">Groq Console</a>.
          </p>
        </div>
        <DialogFooter className="sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save & Start Recording'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
