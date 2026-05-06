import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { useEffect, useState } from "react"

import {
  OauthService,
  type PendingGitHubLoginPublic,
  type UserPublic,
  UsersService,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type ApprovalMode = "create" | "link"

interface ApprovePendingDialogProps {
  pending: PendingGitHubLoginPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ApprovePendingDialog({
  pending,
  open,
  onOpenChange,
}: ApprovePendingDialogProps) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [mode, setMode] = useState<ApprovalMode>(
    pending.email ? "create" : "link",
  )
  const [selectedUserId, setSelectedUserId] = useState<string>("")

  useEffect(() => {
    if (open) {
      setMode(pending.email ? "create" : "link")
      setSelectedUserId("")
    }
  }, [open, pending.email])

  const { data: usersResponse, isLoading: usersLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 500 }),
    enabled: open && mode === "link",
  })

  const approveMutation = useMutation({
    mutationFn: () =>
      OauthService.approvePendingLogin({
        pendingId: pending.id,
        requestBody:
          mode === "create"
            ? { create_user: true }
            : { user_id: selectedUserId },
      }),
    onSuccess: () => {
      showSuccessToast("Pending request approved")
      void queryClient.invalidateQueries({ queryKey: ["pending-github"] })
      void queryClient.invalidateQueries({ queryKey: ["users"] })
      void queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === "users" &&
          q.queryKey[2] === "github-link",
      })
      onOpenChange(false)
    },
    onError: handleError.bind(showErrorToast),
  })

  const canSubmit =
    !approveMutation.isPending &&
    (mode === "create" ? !!pending.email : !!selectedUserId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        data-testid="approve-pending-dialog"
      >
        <DialogHeader>
          <DialogTitle>Approve GitHub sign-in</DialogTitle>
          <DialogDescription>
            Approve the GitHub sign-in for{" "}
            <span className="font-medium">
              {pending.provider_login || pending.provider_account_id}
            </span>
            {pending.email ? ` (${pending.email})` : ""}.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-2">
            <Label>Approval mode</Label>
            <div className="flex flex-col gap-2 rounded-md border p-3">
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="approval-mode"
                  value="create"
                  checked={mode === "create"}
                  disabled={!pending.email}
                  onChange={() => setMode("create")}
                  data-testid="approve-mode-create"
                  className="mt-1"
                />
                <div>
                  <div className="font-medium">Create new user</div>
                  <div className="text-muted-foreground text-xs">
                    {pending.email
                      ? `A new local user will be created with email ${pending.email} (no password) and linked to this GitHub account.`
                      : "Cannot create a new user: pending request has no email."}
                  </div>
                </div>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="approval-mode"
                  value="link"
                  checked={mode === "link"}
                  onChange={() => setMode("link")}
                  data-testid="approve-mode-link"
                  className="mt-1"
                />
                <div>
                  <div className="font-medium">Link to existing user</div>
                  <div className="text-muted-foreground text-xs">
                    Pick an existing local user to link this GitHub identity to.
                  </div>
                </div>
              </label>
            </div>
          </div>

          {mode === "link" && (
            <div className="flex flex-col gap-2">
              <Label>User</Label>
              <Select
                value={selectedUserId}
                onValueChange={setSelectedUserId}
                disabled={usersLoading}
              >
                <SelectTrigger data-testid="approve-link-user-select">
                  <SelectValue placeholder="Select a user" />
                </SelectTrigger>
                <SelectContent>
                  {usersResponse?.data.map((user: UserPublic) => (
                    <SelectItem
                      key={user.id}
                      value={user.id}
                      data-testid={`approve-link-user-${user.email}`}
                    >
                      {user.full_name
                        ? `${user.full_name} (${user.email})`
                        : user.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={approveMutation.isPending}
          >
            Cancel
          </Button>
          <LoadingButton
            type="button"
            loading={approveMutation.isPending}
            disabled={!canSubmit}
            onClick={() => approveMutation.mutate()}
            data-testid="approve-pending-submit"
          >
            <Check />
            Approve
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
