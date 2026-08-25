public class JettyProbe {
  public static void main(String[] a) {
    where("org.apache.hadoop.http.HttpServer2");
    where("org.eclipse.jetty.server.Server");
    // The crux: a Jetty 12 ee8 type that requires Jetty 12 core.
    try {
      Class<?> c = Class.forName("org.eclipse.jetty.ee8.webapp.WebAppContext");
      // force supertype resolution
      c.getSuperclass();
      c.getDeclaredMethods();
      System.out.println("EE8: org.eclipse.jetty.ee8.webapp.WebAppContext links OK");
    } catch (ClassNotFoundException e) {
      System.out.println("EE8: not present (no Jetty 12 ee8 on this classpath)");
    } catch (Throwable t) {
      System.out.println("EE8: " + t.getClass().getName() + ": " + t.getMessage());
    }
  }
  static void where(String n) {
    try {
      Class<?> c = Class.forName(n, false, JettyProbe.class.getClassLoader());
      String s = c.getProtectionDomain().getCodeSource().getLocation().toString();
      System.out.println(n.substring(n.lastIndexOf('.') + 1) + " <- " + s.substring(s.lastIndexOf('/') + 1));
    } catch (Throwable t) {
      System.out.println(n.substring(n.lastIndexOf('.') + 1) + " <- " + t.getClass().getSimpleName());
    }
  }
}
