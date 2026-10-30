import { Tooltip } from '@mui/material';
import { useDirectoryUser } from '../hooks/useDirectoryUser';
import { userName } from '../lib/forms';

interface Props {
  userId: string;
  /** Shown while loading or when the directory no longer knows the user (e.g. a stored snapshot). */
  fallback?: string;
}

/** A userId rendered as the user's name; the id itself stays available on hover. */
export default function UserName({ userId, fallback }: Props) {
  const user = useDirectoryUser(userId);
  return (
    <Tooltip title={userId}>
      <span>{user ? userName(user) : fallback || userId}</span>
    </Tooltip>
  );
}
