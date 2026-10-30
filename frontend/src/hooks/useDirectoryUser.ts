import { useQuery } from '@tanstack/react-query';
import { UsersApi } from '../api/endpoints';

/** One cached directory lookup per userId, shared by every component that shows a user. */
export function directoryUserQuery(userId: string) {
  return {
    queryKey: ['user', userId],
    queryFn: () => UsersApi.get(userId),
    staleTime: 300_000,
    retry: false,
  };
}

/** A stored userId resolved to its directory entry (undefined while loading or unknown). */
export function useDirectoryUser(userId: string | null | undefined) {
  return useQuery({ ...directoryUserQuery(userId ?? ''), enabled: !!userId }).data;
}
