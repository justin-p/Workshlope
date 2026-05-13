import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link2Off } from "lucide-react"
import { useState } from "react"
import { SiGithub } from "react-icons/si"

import { OauthService, type UserPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface ManageGitHubLinkProps {
  user: UserPublic
  onSuccess: () => void
}

function useGitHubLink(userId: string) {
  return useQuery({
    queryKey: ["users", userId, "github-link"],
    queryFn: () => OauthService.getLinkStatus({ userId }),
  })
}

export const ManageGitHubLink = ({
  user,
  onSuccess,
}: ManageGitHubLinkProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { data: link, isLoading } = useGitHubLink(user.id)

  const unlinkMutation = useMutation({
    mutationFn: () => OauthService.adminUnlinkGithub({ userId: user.id }),
    onSuccess: () => {
      showSuccessToast("GitHub account unlinked")
      void queryClient.invalidateQueries({
        queryKey: ["users", user.id, "github-link"],
      })
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
        data-testid={`manage-github-${user.id}`}
      >
        <SiGithub />
        Manage GitHub
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>GitHub for {user.email}</DialogTitle>
          <DialogDescription>
            View whether this user is linked to a GitHub account, and unlink if
            needed. New GitHub sign-ins create a pending request that you can
            approve from the "Pending GitHub" tab.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div
            className="rounded-md border p-3 text-sm"
            data-testid="github-link-status"
          >
            {isLoading ? (
              <span className="text-muted-foreground">Loading status...</span>
            ) : link ? (
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="font-medium">Linked to GitHub</div>
                  <div className="text-muted-foreground text-xs">
                    {link.provider_login || link.provider_account_id}
                  </div>
                </div>
                <LoadingButton
                  type="button"
                  variant="outline"
                  size="sm"
                  loading={unlinkMutation.isPending}
                  onClick={() => unlinkMutation.mutate()}
                  data-testid="unlink-github"
                >
                  <Link2Off />
                  Unlink
                </LoadingButton>
              </div>
            ) : (
              <span className="text-muted-foreground">
                No GitHub account linked.
              </span>
            )}
          </div>
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Close</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
