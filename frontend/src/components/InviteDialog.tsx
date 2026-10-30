import { useState } from 'react';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { InvitesApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import TemporalWindowField from './TemporalWindowField';
import { EMPTY_WINDOW, windowError, type TemporalWindow } from '../lib/forms';
import type { InviteCreated } from '../api/types';

const DEFAULT_DAYS = 14;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

interface Props {
  /** Groups the caller may invite to (managed groups; every active group for admins). */
  groups: string[];
  defaultGroup?: string;
  onClose: () => void;
}

function mailto(invite: InviteCreated): string {
  const subject = `Invitation to the group ${invite.groupName} in catorga`;
  const body =
    `Hello,\n\nyou are invited to join the group "${invite.groupName}" in catorga.\n` +
    `Open this link and sign in with the account of this e-mail address (${invite.email}):\n\n` +
    `${invite.link}\n\nThe invitation can be used once and expires on ` +
    `${new Date(invite.expiresAt).toLocaleDateString()}.\n`;
  return `mailto:${encodeURIComponent(invite.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

// Invite a person to a group by e-mail. The link is personal (single-use, accepted only by
// the account with that e-mail) and shown once: the server keeps only a hash of it.
export default function InviteDialog({ groups, defaultGroup, onClose }: Props) {
  const qc = useQueryClient();
  const [email, setEmail] = useState('');
  const [group, setGroup] = useState(defaultGroup ?? groups[0] ?? '');
  const [days, setDays] = useState(String(DEFAULT_DAYS));
  const [membership, setMembership] = useState<TemporalWindow>(EMPTY_WINDOW);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InviteCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const createMut = useMutation({
    mutationFn: () =>
      InvitesApi.create({
        groupName: group,
        email: email.trim(),
        validDays: Number(days),
        membershipExpiresAt: membership.expiresAt,
      }),
    onSuccess: (invite) => {
      setCreated(invite);
      qc.invalidateQueries({ queryKey: ['invites', invite.groupName] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Failed to create the invitation'),
  });

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.link || created.token);
      setCopied(true);
    } catch {
      setError('Copying failed: select the link and copy it by hand.');
    }
  };

  const daysValue = Number(days);
  const invalid =
    !group ||
    !EMAIL_RE.test(email.trim()) ||
    !Number.isInteger(daysValue) ||
    daysValue < 1 ||
    !!windowError(membership);

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Invite to a group</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}
          {created ? (
            <>
              <Alert severity="success">
                Invitation for {created.email} to {created.groupName} created. Send the link now: it is
                shown only once.
              </Alert>
              <TextField
                label={created.link ? 'Invitation link' : 'Invitation token'}
                value={created.link || created.token}
                InputProps={{ readOnly: true }}
                onFocus={(e) => e.target.select()}
                fullWidth
              />
              {!created.link && (
                <Typography variant="caption" color="text.secondary">
                  No INVITE_LINK_BASE is configured: the invitee opens catorga's /#/invite/&lt;token&gt;.
                </Typography>
              )}
              <Typography variant="body2" color="text.secondary">
                Only the account with this e-mail address can accept it, once, until{' '}
                {new Date(created.expiresAt).toLocaleString()}.
              </Typography>
            </>
          ) : (
            <>
              <TextField
                label="E-mail of the person"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                helperText="They must sign in with the account that has this e-mail address."
                autoFocus
              />
              <TextField select label="Group" value={group} onChange={(e) => setGroup(e.target.value)}>
                {groups.map((g) => (
                  <MenuItem key={g} value={g}>
                    {g}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Link valid for (days)"
                type="number"
                value={days}
                onChange={(e) => setDays(e.target.value)}
                inputProps={{ min: 1 }}
              />
              <Typography variant="caption" color="text.secondary">
                Optional end of the membership (for students / guests):
              </Typography>
              <TemporalWindowField value={membership} onChange={setMembership} expiryOnly />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        {created ? (
          <>
            <Button onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
            {created.link && <Button href={mailto(created)}>Open in e-mail</Button>}
            <Button variant="contained" onClick={onClose}>
              Done
            </Button>
          </>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="contained"
              disabled={invalid || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              Create invitation
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
