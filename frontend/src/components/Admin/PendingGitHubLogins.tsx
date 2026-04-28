import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Github, X } from "lucide-react"
import { useState } from "react"

import { OauthService, type PendingGitHubLoginPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { ApprovePendingDialog } from "./ApprovePendingDialog"

const PENDING_QUERY_KEY = ["pending-github"]

function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function PendingGitHubLogins() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [approving, setApproving] = useState<PendingGitHubLoginPublic | null>(
    null,
  )

  const { data, isLoading } = useQuery({
    queryKey: PENDING_QUERY_KEY,
    queryFn: () => OauthService.listPendingLogins({}),
  })

  const denyMutation = useMutation({
    mutationFn: (pendingId: string) =>
      OauthService.denyPendingLogin({ pendingId }),
    onSuccess: () => {
      showSuccessToast("Pending request denied")
      void queryClient.invalidateQueries({ queryKey: PENDING_QUERY_KEY })
    },
    onError: handleError.bind(showErrorToast),
  })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, idx) => (
          <Skeleton key={idx} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  const rows = data?.data ?? []

  return (
    <div className="flex flex-col gap-4" data-testid="pending-github-logins">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>GitHub login</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Full name</TableHead>
            <TableHead>Last seen</TableHead>
            <TableHead>Attempts</TableHead>
            <TableHead className="text-right">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={6}
                className="h-32 text-center text-muted-foreground"
                data-testid="pending-github-empty"
              >
                No pending GitHub sign-in requests.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow
                key={row.id}
                data-testid={`pending-row-${row.provider_account_id}`}
              >
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Github className="size-4 text-muted-foreground" />
                    <span className="font-medium">
                      {row.provider_login || row.provider_account_id}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {row.email || "-"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {row.full_name || "-"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(row.last_seen_at)}
                </TableCell>
                <TableCell>{row.attempt_count}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => setApproving(row)}
                      data-testid={`pending-approve-${row.provider_account_id}`}
                    >
                      <Check />
                      Approve
                    </Button>
                    <LoadingButton
                      type="button"
                      size="sm"
                      variant="outline"
                      loading={
                        denyMutation.isPending &&
                        denyMutation.variables === row.id
                      }
                      onClick={() => denyMutation.mutate(row.id)}
                      data-testid={`pending-deny-${row.provider_account_id}`}
                    >
                      <X />
                      Deny
                    </LoadingButton>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {approving && (
        <ApprovePendingDialog
          pending={approving}
          open={!!approving}
          onOpenChange={(open) => {
            if (!open) setApproving(null)
          }}
        />
      )}
    </div>
  )
}
