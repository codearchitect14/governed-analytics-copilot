import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Breadcrumbs, Button, Input, Section, Textarea } from "../../components/ui";
import { CONTACT_TOPICS } from "../../lib/content";
import { submitContact } from "../../lib/api";

export const contactSchema = z.object({
  name: z.string().trim().min(2, "Enter your name.").max(120),
  email: z.email("Enter a valid email address.").max(254),
  company: z.string().trim().max(120).optional(),
  topic: z.enum(CONTACT_TOPICS, { error: "Choose a topic." }),
  message: z.string().trim().min(10, "Write at least 10 characters.").max(2000, "Keep the message under 2000 characters."),
  consent: z.literal(true, { error: "Please agree before sending." }),
  website: z.string().max(0).optional(),
});

export type ContactForm = z.infer<typeof contactSchema>;

export default function Contact() {
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ContactForm>({
    resolver: zodResolver(contactSchema),
    defaultValues: { topic: CONTACT_TOPICS[0], consent: undefined as unknown as true },
  });

  async function onSubmit(values: ContactForm) {
    setStatus("sending");
    try {
      await submitContact({
        name: values.name,
        email: values.email,
        company: values.company || null,
        topic: values.topic,
        message: values.message,
        consent: true,
      });
      setStatus("sent");
      reset();
    } catch {
      setStatus("failed");
    }
  }

  return (
    <>
      <section className="py-10 md:py-14">
        <div className="container-page">
          <Breadcrumbs items={[{ label: "Home", to: "/" }, { label: "Contact" }]} />
          <h1 className="mt-4 text-4xl">Contact</h1>
          <p className="mt-4 max-w-2xl text-lg text-ink-muted">Ask for a walkthrough or send a technical question. A person reads every message.</p>
        </div>
      </section>
      <Section>
        <form className="grid max-w-2xl gap-5" onSubmit={handleSubmit(onSubmit)} noValidate aria-describedby="contact-status">
          <Input label="Name" autoComplete="name" error={errors.name?.message} {...register("name")} />
          <Input label="Work email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
          <Input label="Company (optional)" autoComplete="organization" error={errors.company?.message} {...register("company")} />
          <div className="flex flex-col gap-1">
            <label htmlFor="topic" className="text-sm font-semibold">Topic</label>
            <select id="topic" className="min-h-11 rounded-md border border-line bg-page px-3 text-base" aria-invalid={errors.topic ? true : undefined} {...register("topic")}>
              {CONTACT_TOPICS.map((topic) => (
                <option key={topic} value={topic}>{topic}</option>
              ))}
            </select>
            {errors.topic ? <p role="alert" className="text-xs text-error">{errors.topic.message}</p> : null}
          </div>
          <Textarea label="Message" error={errors.message?.message} {...register("message")} />
          <div className="flex items-start gap-3">
            <input id="consent" type="checkbox" className="mt-1 h-5 w-5" aria-invalid={errors.consent ? true : undefined} {...register("consent")} />
            <label htmlFor="consent" className="text-sm">
              I agree that my details are kept to answer this message. See the <a href="/legal/privacy">privacy notice</a>.
            </label>
          </div>
          {errors.consent ? <p role="alert" className="text-xs text-error">{errors.consent.message}</p> : null}
          {/* Honeypot: hidden from people, filled in by simple bots */}
          <div className="absolute -left-[9999px]" aria-hidden="true">
            <label htmlFor="website">Website</label>
            <input id="website" tabIndex={-1} autoComplete="off" {...register("website")} />
          </div>
          <div>
            <Button type="submit" variant="accent" disabled={isSubmitting || status === "sending"}>
              {status === "sending" ? "Sending…" : "Send message"}
            </Button>
          </div>
          <p id="contact-status" role="status" className="text-sm">
            {status === "sent" ? "Thank you. Your message has been received." : null}
            {status === "failed" ? "The message could not be sent. Please try again later." : null}
          </p>
        </form>
      </Section>
    </>
  );
}
