public class RtProbe {
  public static void main(String[] a) {
    try {
      Class<?> c = Class.forName("org.apache.hadoop.http.HttpServer2");
      System.out.println("HttpServer2 loaded from " +
        c.getProtectionDomain().getCodeSource().getLocation());
      // Force the ee8 types HttpServer2 declares to resolve.
      for (java.lang.reflect.Field f : c.getDeclaredFields()) {
        System.out.println("  field " + f.getName() + " : " + f.getType().getName());
      }
      Class<?> b = Class.forName("org.apache.hadoop.http.HttpServer2$Builder");
      Object bd = b.getDeclaredConstructor().newInstance();
      System.out.println("Builder instantiated: " + bd.getClass().getName());
      System.out.println("RESULT: no linkage error");
    } catch (Throwable t) {
      System.out.println("RESULT: " + t.getClass().getName() + ": " + t.getMessage());
    }
  }
}
