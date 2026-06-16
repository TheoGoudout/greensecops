import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import type { LLMProvider, OrganizationPublic } from "@/client"
import { OrganizationsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"

function OrgAICard({ org }: { org: OrganizationPublic }) {
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState<LLMProvider>(
    org.default_llm_provider,
  )
  const [model, setModel] = useState<string>(org.default_llm_model ?? "")

  const { data: providersData } = useQuery({
    queryKey: ["ai-providers"],
    queryFn: OrganizationsService.listAiProviders,
  })

  const mutation = useMutation({
    mutationFn: () =>
      OrganizationsService.updateOrgAiPreferences({
        orgId: org.id,
        requestBody: {
          default_llm_provider: provider,
          default_llm_model: model || null,
        },
      }),
    onSuccess: () => {
      toast.success(`AI preferences saved for ${org.name}`)
      queryClient.invalidateQueries({ queryKey: ["organizations"] })
    },
    onError: () => {
      toast.error("Failed to save AI preferences")
    },
  })

  const selectedProviderInfo = providersData?.providers.find(
    (p) => p.id === provider,
  )
  const defaultModel = selectedProviderInfo?.default_model ?? ""
  const modelOptions = selectedProviderInfo?.models ?? []

  const handleProviderChange = (val: LLMProvider) => {
    setProvider(val)
    const info = providersData?.providers.find((p) => p.id === val)
    setModel(info?.default_model ?? "")
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{org.name}</CardTitle>
        <CardDescription>
          Configure the LLM provider and model used to generate fixes for this
          organization.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-2">
          <Label htmlFor={`provider-${org.id}`}>Provider</Label>
          <Select
            value={provider}
            onValueChange={(v) => handleProviderChange(v as LLMProvider)}
          >
            <SelectTrigger id={`provider-${org.id}`}>
              <SelectValue placeholder="Select provider" />
            </SelectTrigger>
            <SelectContent>
              {providersData?.providers.map((p) => (
                <SelectItem key={p.id} value={p.id} disabled={!p.available}>
                  {p.name}
                  {!p.available && " (no API key configured)"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid gap-2">
          <Label htmlFor={`model-${org.id}`}>Model</Label>
          {modelOptions.length > 0 ? (
            <Select value={model || defaultModel} onValueChange={setModel}>
              <SelectTrigger id={`model-${org.id}`}>
                <SelectValue placeholder={`Default: ${defaultModel}`} />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                    {m === defaultModel && " (default)"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              id={`model-${org.id}`}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={defaultModel || "e.g. llama3.2"}
            />
          )}
          <p className="text-xs text-muted-foreground">
            Leave blank to use the provider default ({defaultModel || "—"}).
          </p>
        </div>

        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="self-start"
        >
          {mutation.isPending ? "Saving…" : "Save preferences"}
        </Button>
      </CardContent>
    </Card>
  )
}

export default function AISettings() {
  const { data: orgs, isLoading } = useQuery({
    queryKey: ["organizations"],
    queryFn: OrganizationsService.listMyOrganizations,
  })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (!orgs || orgs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        No organizations found. Install the GitHub App to connect your first
        organization.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4 max-w-lg">
      {orgs.map((org) => (
        <OrgAICard key={org.id} org={org} />
      ))}
    </div>
  )
}
