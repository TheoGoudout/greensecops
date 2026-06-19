import { useFormContext } from "react-hook-form"
import { Checkbox } from "@/components/ui/checkbox"
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"

interface UserFormFieldsProps {
  mode: "create" | "edit"
}

export function UserFormFields({ mode }: UserFormFieldsProps) {
  const { control } = useFormContext()

  return (
    <>
      <FormField
        control={control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Email <span className="text-destructive">*</span>
            </FormLabel>
            <FormControl>
              <Input placeholder="Email" type="email" {...field} required />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="full_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Full Name</FormLabel>
            <FormControl>
              <Input placeholder="Full name" type="text" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="password"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Set Password{" "}
              {mode === "create" && <span className="text-destructive">*</span>}
            </FormLabel>
            <FormControl>
              <Input
                placeholder="Password"
                type="password"
                {...field}
                required={mode === "create"}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="confirm_password"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Confirm Password{" "}
              {mode === "create" && <span className="text-destructive">*</span>}
            </FormLabel>
            <FormControl>
              <Input
                placeholder="Password"
                type="password"
                {...field}
                required={mode === "create"}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="is_superuser"
        render={({ field }) => (
          <FormItem className="flex items-center gap-3 space-y-0">
            <FormControl>
              <Checkbox
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            </FormControl>
            <FormLabel className="font-normal">Is superuser?</FormLabel>
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="is_active"
        render={({ field }) => (
          <FormItem className="flex items-center gap-3 space-y-0">
            <FormControl>
              <Checkbox
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            </FormControl>
            <FormLabel className="font-normal">Is active?</FormLabel>
          </FormItem>
        )}
      />
    </>
  )
}
